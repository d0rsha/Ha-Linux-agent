import asyncio
import logging

import httpx

from .chat import ChatService, SQLiteSessionStore
from .config import Settings
from .storage import SQLiteStore

LOGGER = logging.getLogger("ha_agent.signal")


class SignalBot:
    def __init__(self, settings: Settings) -> None:
        if not settings.signal_number:
            raise ValueError("SIGNAL_NUMBER is required")
        self.settings = settings
        self.base_url = settings.signal_api_url.rstrip("/")
        self.number = settings.signal_number
        self.allowed_senders = settings.signal_allowed_sender_set
        store = SQLiteStore(
            settings.state_db_path,
            max_messages_per_session=settings.chat_context_messages,
            conversation_retention_days=settings.conversation_retention_days,
            audit_retention_days=settings.audit_retention_days,
        )
        self.service = ChatService(
            settings,
            SQLiteSessionStore(store, secrets=settings.secrets_for_redaction),
        )
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(40.0, connect=10.0))

    async def close(self) -> None:
        await self._client.aclose()

    async def send_message(self, recipient: str, text: str) -> None:
        chunks = [text[i : i + 3500] for i in range(0, len(text), 3500)] or ["(empty response)"]
        for chunk in chunks:
            response = await self._client.post(
                f"{self.base_url}/v2/send",
                json={"message": chunk, "number": self.number, "recipients": [recipient]},
            )
            response.raise_for_status()

    @staticmethod
    def _extract_message(envelope: dict) -> tuple[str, str] | None:
        source = envelope.get("sourceNumber") or envelope.get("source")
        data_message = envelope.get("dataMessage") or {}
        text = (data_message.get("message") or "").strip()
        if not source or not text:
            return None
        return str(source), text

    async def _handle_message(self, sender: str, text: str) -> None:
        if sender == self.number:
            return
        if self.allowed_senders and sender not in self.allowed_senders:
            LOGGER.warning("rejected Signal sender %s", sender)
            return

        session_id = f"signal-{sender}"
        if text in {"/start", "/help"}:
            await self.send_message(
                sender,
                "HA Linux Agent is ready. Ask a Home Assistant question normally. "
                "Use /approve-sensitive to grant one sensitive action for the next request, "
                "or /clear to clear conversation context.",
            )
            return
        if text == "/clear":
            self.service.clear(session_id)
            await self.send_message(sender, "Conversation context cleared.")
            return
        if text == "/approve-sensitive":
            self.service.approve_sensitive_once(session_id)
            await self.send_message(
                sender,
                f"One sensitive action is approved for the next request for {self.settings.chat_sensitive_approval_ttl_seconds} seconds.",
            )
            return
        if text.startswith("/"):
            await self.send_message(sender, "Unknown command. Use /help.")
            return

        try:
            answer = await self.service.ask(sender, session_id, text)
        except Exception:
            LOGGER.exception("Signal request failed")
            answer = "The agent request failed. Check the server logs; no successful action is being claimed."
        await self.send_message(sender, answer)

    async def run_forever(self) -> None:
        LOGGER.info("Signal transport started")
        try:
            while True:
                try:
                    response = await self._client.get(f"{self.base_url}/v1/receive/{self.number}")
                    response.raise_for_status()
                    body = response.json()
                    for item in body if isinstance(body, list) else []:
                        envelope = item.get("envelope") or item
                        parsed = self._extract_message(envelope)
                        if parsed:
                            await self._handle_message(*parsed)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    LOGGER.exception("Signal polling failed")
                await asyncio.sleep(self.settings.signal_poll_interval_seconds)
        finally:
            await self.close()


async def run_signal(settings: Settings) -> None:
    await SignalBot(settings).run_forever()
