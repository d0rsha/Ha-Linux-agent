from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class StoredMessage:
    role: str
    text: str
    created_at: float


@dataclass(frozen=True)
class StoredSession:
    session_id: str
    messages: list[StoredMessage]
    approve_sensitive_until: float = 0.0


@dataclass(frozen=True)
class MemoryItem:
    key: str
    value: str
    created_at: float
    updated_at: float


class SQLiteStore:
    """Durable, inspectable SQLite state store for conversations, memory and audit metadata."""

    def __init__(
        self,
        path: str,
        *,
        max_messages_per_session: int = 20,
        conversation_retention_days: int = 30,
        audit_retention_days: int = 90,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_messages_per_session = max(1, max_messages_per_session)
        self.conversation_retention_days = max(0, conversation_retention_days)
        self.audit_retention_days = max(0, audit_retention_days)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 10000")
        return conn

    def _migrate(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            row = conn.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
            version = int(row["value"]) if row else 0
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema version {version} is newer than supported {SCHEMA_VERSION}"
                )
            if version < 1:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS conversations (
                        session_id TEXT PRIMARY KEY,
                        approve_sensitive_until REAL NOT NULL DEFAULT 0,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS conversation_messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL REFERENCES conversations(session_id) ON DELETE CASCADE,
                        role TEXT NOT NULL,
                        text TEXT NOT NULL,
                        created_at REAL NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_conversation_messages_session
                        ON conversation_messages(session_id, id DESC);
                    CREATE INDEX IF NOT EXISTS idx_conversation_messages_created
                        ON conversation_messages(created_at);

                    CREATE TABLE IF NOT EXISTS memories (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_memories_updated
                        ON memories(updated_at DESC);

                    CREATE TABLE IF NOT EXISTS tool_audit (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        correlation_id TEXT NOT NULL,
                        session_id TEXT,
                        provider TEXT NOT NULL,
                        model TEXT NOT NULL,
                        event TEXT NOT NULL,
                        tool_name TEXT NOT NULL,
                        tier TEXT NOT NULL,
                        decision TEXT NOT NULL,
                        success INTEGER,
                        duration_ms REAL,
                        reason TEXT,
                        argument_keys TEXT NOT NULL,
                        created_at REAL NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_tool_audit_created
                        ON tool_audit(created_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_tool_audit_correlation
                        ON tool_audit(correlation_id);
                    """
                )
                conn.execute(
                    "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )

    def load_session(self, session_id: str) -> StoredSession:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT approve_sensitive_until FROM conversations WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            messages = conn.execute(
                """
                SELECT role, text, created_at
                FROM conversation_messages
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, self.max_messages_per_session),
            ).fetchall()
        return StoredSession(
            session_id=session_id,
            messages=[
                StoredMessage(str(item["role"]), str(item["text"]), float(item["created_at"]))
                for item in reversed(messages)
            ],
            approve_sensitive_until=float(row["approve_sensitive_until"]) if row else 0.0,
        )

    def save_session(self, session: StoredSession) -> None:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversations(session_id, approve_sensitive_until, created_at, updated_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    approve_sensitive_until = excluded.approve_sensitive_until,
                    updated_at = excluded.updated_at
                """,
                (session.session_id, session.approve_sensitive_until, now, now),
            )
            conn.execute("DELETE FROM conversation_messages WHERE session_id = ?", (session.session_id,))
            conn.executemany(
                """
                INSERT INTO conversation_messages(session_id, role, text, created_at)
                VALUES(?, ?, ?, ?)
                """,
                [
                    (session.session_id, item.role, item.text, item.created_at)
                    for item in session.messages[-self.max_messages_per_session :]
                ],
            )
        self.prune()

    def clear_session(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM conversations WHERE session_id = ?", (session_id,))

    def list_memories(self, *, limit: int = 20, query: str | None = None) -> list[MemoryItem]:
        limit = max(1, min(limit, 200))
        with self._connect() as conn:
            if query:
                pattern = f"%{query}%"
                rows = conn.execute(
                    """
                    SELECT key, value, created_at, updated_at FROM memories
                    WHERE key LIKE ? OR value LIKE ?
                    ORDER BY updated_at DESC, key ASC
                    LIMIT ?
                    """,
                    (pattern, pattern, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT key, value, created_at, updated_at FROM memories
                    ORDER BY updated_at DESC, key ASC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [
            MemoryItem(
                key=str(row["key"]),
                value=str(row["value"]),
                created_at=float(row["created_at"]),
                updated_at=float(row["updated_at"]),
            )
            for row in rows
        ]

    def set_memory(self, key: str, value: str) -> None:
        key = key.strip()
        value = value.strip()
        if not key or not value:
            raise ValueError("memory key and value must be non-empty")
        if len(key) > 120:
            raise ValueError("memory key is too long")
        if len(value) > 4000:
            raise ValueError("memory value is too long")
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memories(key, value, created_at, updated_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, value, now, now),
            )

    def delete_memory(self, key: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM memories WHERE key = ?", (key,))
            return cursor.rowcount > 0

    def record_tool_event(
        self,
        *,
        correlation_id: str,
        session_id: str | None,
        provider: str,
        model: str,
        event: str,
        tool_name: str,
        tier: str,
        decision: str,
        argument_keys: Iterable[str],
        success: bool | None = None,
        duration_ms: float | None = None,
        reason: str | None = None,
        created_at: float | None = None,
    ) -> None:
        # Deliberately store only argument names and result metadata, never raw arguments/results.
        keys = ",".join(sorted(str(item) for item in argument_keys))
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tool_audit(
                    correlation_id, session_id, provider, model, event, tool_name,
                    tier, decision, success, duration_ms, reason, argument_keys, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    correlation_id,
                    session_id,
                    provider,
                    model,
                    event,
                    tool_name,
                    tier,
                    decision,
                    None if success is None else int(success),
                    duration_ms,
                    reason,
                    keys,
                    created_at if created_at is not None else time.time(),
                ),
            )
        self.prune()

    def list_audit(self, *, limit: int = 100) -> list[dict[str, object]]:
        limit = max(1, min(limit, 500))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tool_audit ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def prune(self) -> None:
        now = time.time()
        with self._connect() as conn:
            if self.conversation_retention_days > 0:
                cutoff = now - self.conversation_retention_days * 86400
                conn.execute("DELETE FROM conversations WHERE updated_at < ?", (cutoff,))
            if self.audit_retention_days > 0:
                cutoff = now - self.audit_retention_days * 86400
                conn.execute("DELETE FROM tool_audit WHERE created_at < ?", (cutoff,))
