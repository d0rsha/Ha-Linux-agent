from pathlib import Path

from ha_agent.storage import SQLiteStore, StoredMessage, StoredSession


def test_sqlite_session_survives_reload_and_is_bounded(tmp_path: Path):
    path = tmp_path / "agent.db"
    store = SQLiteStore(str(path), max_messages_per_session=3)
    store.save_session(
        StoredSession(
            "telegram-1-2",
            [
                StoredMessage("user", "one", 1.0),
                StoredMessage("assistant", "two", 2.0),
                StoredMessage("user", "three", 3.0),
                StoredMessage("assistant", "four", 4.0),
            ],
            approve_sensitive_until=123.0,
        )
    )

    loaded = SQLiteStore(str(path), max_messages_per_session=3).load_session("telegram-1-2")
    assert [item.text for item in loaded.messages] == ["two", "three", "four"]
    assert loaded.approve_sensitive_until == 123.0


def test_memory_is_explicit_inspectable_and_independently_deletable(tmp_path: Path):
    store = SQLiteStore(str(tmp_path / "agent.db"))
    store.set_memory("preferred_temperature", "21 C")
    store.set_memory("server_name", "rpi3")

    assert {item.key for item in store.list_memories(limit=10)} == {
        "preferred_temperature",
        "server_name",
    }
    assert store.delete_memory("preferred_temperature") is True
    assert [item.key for item in store.list_memories(limit=10)] == ["server_name"]


def test_audit_stores_metadata_not_raw_arguments_or_results(tmp_path: Path):
    path = tmp_path / "agent.db"
    store = SQLiteStore(str(path))
    store.record_tool_event(
        correlation_id="corr-1",
        session_id="telegram-1-2",
        provider="openai",
        model="test-model",
        event="tool_executed",
        tool_name="GetLiveContext",
        tier="read",
        decision="allow",
        argument_keys=["entity_id", "token"],
        success=True,
        duration_ms=12.5,
    )

    row = store.list_audit(limit=1)[0]
    assert row["tool_name"] == "GetLiveContext"
    assert row["provider"] == "openai"
    assert row["model"] == "test-model"
    assert row["success"] == 1
    assert row["duration_ms"] == 12.5
    assert row["argument_keys"] == "entity_id,token"

    raw = path.read_bytes()
    assert b"raw-secret-value" not in raw
    assert b"raw-tool-result" not in raw


def test_schema_version_is_recorded(tmp_path: Path):
    path = tmp_path / "agent.db"
    SQLiteStore(str(path))
    import sqlite3

    with sqlite3.connect(path) as conn:
        version = conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0]
    assert version == "1"
