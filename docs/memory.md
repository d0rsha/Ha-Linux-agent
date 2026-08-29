# SQLite conversation, memory and audit store

The agent uses one local SQLite database for three separate concerns:

1. conversation/session persistence
2. explicitly selected long-term memory
3. tool-call audit metadata

The default path is `/data/ha-agent.db`, which is already inside the Compose `ha-agent-data` named volume.

## Long-term memory

Memory is intentionally explicit. The model may read the bounded selected memory context, but it is not given tools to create, update or delete memory autonomously.

Inspect memory:

```bash
docker compose run --rm -T ha-agent memory list
```

Add or update one fact:

```bash
docker compose run --rm -T ha-agent memory set preferred_temperature "21 C"
```

Delete one fact without touching conversations or audit history:

```bash
docker compose run --rm -T ha-agent memory delete preferred_temperature
```

`MEMORY_CONTEXT_ITEMS` limits how many recently updated items are injected into an agent request. Memory is factual context only; it does not grant permissions or override the system prompt.

Do not use long-term memory for passwords, API keys, access tokens or other credentials. Values matching configured agent secrets are refused by the CLI and runtime conversation persistence redacts configured secrets before storage.

## Conversation persistence

Telegram sessions now use SQLite instead of the v0.4 JSON session files. Session IDs, bounded recent messages and the short-lived sensitive approval timestamp survive container restarts.

`CHAT_CONTEXT_MESSAGES` bounds the number of messages stored per session. `CONVERSATION_RETENTION_DAYS` removes sessions that have not been updated within the configured retention period. Set retention to `0` to disable age-based pruning.

The legacy `JsonSessionStore` remains in code for compatibility, but Telegram no longer uses it.

## Tool-call audit

Every tool authorization/execution event can be inspected from SQLite:

```bash
docker compose run --rm -T ha-agent audit --limit 100
```

Stored audit fields include correlation ID, optional session ID, provider, model, event, tool name, policy tier/decision, success/failure, execution duration, reason metadata, argument *names*, and timestamp.

Raw tool arguments and raw tool results are deliberately not stored in SQLite. This reduces the chance of credentials or sensitive Home Assistant data being copied into the audit database.

`AUDIT_RETENTION_DAYS` controls automatic age-based pruning. Set it to `0` to disable pruning. The existing optional JSONL audit log remains available independently through `AUDIT_LOG_PATH`.

## Schema versioning

The database contains `schema_meta.schema_version`. Startup migrations are applied sequentially by `SQLiteStore`. A database created by a newer unsupported schema version is rejected instead of being silently downgraded.

## Backup

Stop writers or create a SQLite-safe backup before copying the database. The database is local state and must not be committed to Git.
