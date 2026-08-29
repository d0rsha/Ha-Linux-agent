from pathlib import Path

import pytest

from ha_agent.chat import ChatMessage, ChatSession, JsonSessionStore, RateLimiter


def test_json_session_store_survives_reload(tmp_path: Path):
    store = JsonSessionStore(str(tmp_path), max_messages=3)
    session = ChatSession(
        session_id="telegram-1-2",
        messages=[
            ChatMessage("user", "one", 1.0),
            ChatMessage("assistant", "two", 2.0),
            ChatMessage("user", "three", 3.0),
            ChatMessage("assistant", "four", 4.0),
        ],
        approve_sensitive_until=123.0,
    )
    store.save(session)

    loaded = JsonSessionStore(str(tmp_path), max_messages=3).load("telegram-1-2")
    assert [message.text for message in loaded.messages] == ["two", "three", "four"]
    assert loaded.approve_sensitive_until == 123.0


def test_session_ids_cannot_escape_store_directory(tmp_path: Path):
    store = JsonSessionStore(str(tmp_path))
    with pytest.raises(ValueError, match="invalid session id"):
        store.load("../secret")


def test_rate_limiter_blocks_immediate_duplicate():
    limiter = RateLimiter(60)
    assert limiter.allow("user-1") is True
    assert limiter.allow("user-1") is False
    assert limiter.allow("user-2") is True
