import asyncio
import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from .agent import ask_home
from .config import Settings
from .models import ToolCall
from .policy import PolicyDecision


@dataclass(frozen=True)
class ChatMessage:
    role: str
    text: str
    created_at: float


@dataclass
class ChatSession:
    session_id: str
    messages: list[ChatMessage] = field(default_factory=list)
    approve_sensitive_until: float = 0.0


class SessionStore(Protocol):
    def load(self, session_id: str) -> ChatSession: ...
    def save(self, session: ChatSession) -> None: ...


class JsonSessionStore:
    """Small persistent store for v0.4 chat state; SQLite migration is tracked separately."""

    def __init__(self, directory: str, max_messages: int = 20) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.max_messages = max_messages

    def _path(self, session_id: str) -> Path:
        safe = "".join(ch for ch in session_id if ch.isalnum() or ch in "-_.")
        if not safe or safe != session_id:
            raise ValueError("invalid session id")
        return self.directory / f"{safe}.json"

    def load(self, session_id: str) -> ChatSession:
        path = self._path(session_id)
        if not path.exists():
            return ChatSession(session_id=session_id)
        raw = json.loads(path.read_text(encoding="utf-8"))
        messages = [ChatMessage(**item) for item in raw.get("messages", [])][-self.max_messages :]
        return ChatSession(
            session_id=session_id,
            messages=messages,
            approve_sensitive_until=float(raw.get("approve_sensitive_until", 0.0)),
        )

    def save(self, session: ChatSession) -> None:
        path = self._path(session.session_id)
        payload = {
            "session_id": session.session_id,
            "messages": [asdict(item) for item in session.messages[-self.max_messages :]],
            "approve_sensitive_until": session.approve_sensitive_until,
        }
        fd, temp_name = tempfile.mkstemp(prefix=path.name, dir=str(self.directory))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)


class RateLimiter:
    def __init__(self, min_interval_seconds: float) -> None:
        self.min_interval_seconds = min_interval_seconds
        self._last: dict[str, float] = {}

    def allow(self, identity: str) -> bool:
        now = time.monotonic()
        previous = self._last.get(identity, 0.0)
        if now - previous < self.min_interval_seconds:
            return False
        self._last[identity] = now
        return True


class ChatService:
    def __init__(self, settings: Settings, store: SessionStore) -> None:
        self.settings = settings
        self.store = store
        self.rate_limiter = RateLimiter(settings.chat_min_interval_seconds)
        self._session_locks: dict[str, asyncio.Lock] = {}

    def approve_sensitive_once(self, session_id: str) -> None:
        session = self.store.load(session_id)
        session.approve_sensitive_until = time.time() + self.settings.chat_sensitive_approval_ttl_seconds
        self.store.save(session)

    def clear(self, session_id: str) -> None:
        self.store.save(ChatSession(session_id=session_id))

    async def ask(self, identity: str, session_id: str, text: str) -> str:
        if not self.rate_limiter.allow(identity):
            return "Request rate limit exceeded. Try again shortly."
        lock = self._session_locks.setdefault(session_id, asyncio.Lock())
        if lock.locked():
            return "A request is already running for this conversation."
        async with lock:
            session = self.store.load(session_id)
            context = "\n".join(f"{m.role}: {m.text}" for m in session.messages[-self.settings.chat_context_messages :])
            question = text if not context else f"Conversation context:\n{context}\n\nCurrent user request:\n{text}"
            approval_available = session.approve_sensitive_until >= time.time()
            approval_consumed = False

            def _confirm(_call: ToolCall, _decision: PolicyDecision) -> bool:
                nonlocal approval_consumed
                if approval_available and not approval_consumed:
                    approval_consumed = True
                    return True
                return False

            answer = await ask_home(self.settings, question, confirm_sensitive=_confirm)
            if approval_consumed:
                session.approve_sensitive_until = 0.0
            now = time.time()
            session.messages.extend([ChatMessage("user", text, now), ChatMessage("assistant", answer, time.time())])
            session.messages = session.messages[-self.settings.chat_context_messages :]
            self.store.save(session)
            return answer
