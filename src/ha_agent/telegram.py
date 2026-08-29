import asyncio
import logging

import httpx

from .chat import ChatService, JsonSessionStore
from .config import Settings

LOGGER = logging.getLogger("ha_agent.telegram")


class TelegramBot:
    def __init__(self, settings: Settings) -> None:
        if not settings.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required")
        self.settings = settings
        self.base_url = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
        self.allowed_user_ids = settings.telegram_allowed_user_ids
        self.service = ChatService(
            settings,
            JsonSessionStore(settings.chat_session_dir, max_messages=settings.chat_context_messages),
        )
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(40.0, connect=10.0))

    async def close(self) -> None:
        await self._client.aclose()

    async def _call(self, method: str, payload: dict | None = None) -> dict:
        response = await self._client.post(f"{self.base_url}/{method}", json=payload or {})
        response.raise_for_status()
        body = response.json()
        if not body.get("ok"):
            raise RuntimeError(f"Telegram API {method} failed")
        return body

    async def send_message(self, chat_id: int, text: str) -> None:
        # Telegram text messages are limited to 4096 chars. Keep chunks conservative.
        chunks = [text[i : i + 3900] for i in range(0, len(text), 3900)] or ["(empty response)"]
        for chunk in chunks:
            await self._call("sendMessage", {"chat_id": chat_id, "text": chunk})

    async def _handle_message(self, message: dict) -> None:
        user = message.get("from") or {}
        user_id = int(user.get("id", 0))
        chat = message.get("chat") or {}
        chat_id = int(chat.get("id", 0))
        text = (message.get("text") or "").strip()
        if not chat_id or not text:
            return
        if self.allowed_user_ids and user_id not in self.allowed_user_ids:
            LOGGER.warning("rejected Telegram user id %s", user_id)
            return

        session_id = f"telegram-{chat_id}-{user_id}"
        if text == "/start" or text == "/help":
            await self.send_message(
                chat_id,
                "HA Linux Agent is ready. Ask a Home Assistant question normally. "
                "Use /approve-sensitive to grant one sensitive action for the next request, "
                "or /clear to clear conversation context.",
            )
            return
        if text == "/clear":
            self.service.clear(session_id)
            await self.send_message(chat_id, "Conversation context cleared.")
            return
        if text == "/approve-sensitive":
            self.service.approve_sensitive_once(session_id)
            await self.send_message(
                chat_id,
                f"One sensitive action is approved for the next request for {self.settings.chat_sensitive_approval_ttl_seconds} seconds.",
            )
            return
        if text.startswith("/"):
            await self.send_message(chat_id, "Unknown command. Use /help.")
            return

        try:
            answer = await self.service.ask(str(user_id), session_id, text)
        except Exception:
            LOGGER.exception("Telegram request failed")
            answer = "The agent request failed. Check the server logs; no successful action is being claimed."
        await self.send_message(chat_id, answer)

    async def run_forever(self) -> None:
        offset = 0
        LOGGER.info("Telegram transport started")
        try:
            while True:
                try:
                    body = await self._call(
                        "getUpdates",
                        {"offset": offset, "timeout": 30, "allowed_updates": ["message"]},
                    )
                    for update in body.get("result", []):
                        offset = max(offset, int(update["update_id"]) + 1)
                        message = update.get("message")
                        if message:
                            await self._handle_message(message)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    LOGGER.exception("Telegram polling failed")
                    await asyncio.sleep(5)
        finally:
            await self.close()


async def run_telegram(settings: Settings) -> None:
    await TelegramBot(settings).run_forever()
