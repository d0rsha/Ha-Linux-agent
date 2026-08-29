# Telegram chat transport

v0.4 adds Telegram as the first persistent remote chat transport. The core agent remains transport-independent: Telegram calls `ChatService`, which owns session context, rate limiting, per-session serialization and sensitive-action approval.

## Setup

Create a Telegram bot with BotFather and configure `.env`:

```env
TELEGRAM_BOT_TOKEN=123456:replace-me
TELEGRAM_ALLOWED_USERS=123456789
```

`TELEGRAM_ALLOWED_USERS` must contain explicit numeric Telegram user IDs. Unknown users are ignored and cannot reach the model or Home Assistant tools.

Start the transport with the Compose profile:

```bash
docker compose --profile telegram up -d ha-agent-telegram
```

Or run it directly:

```bash
docker compose run --rm -T ha-agent telegram
```

## Conversation state

Chat context is stored under `CHAT_SESSION_DIR` (default `/data/chat`) and the Compose configuration mounts a named `ha-agent-data` volume. The JSON store is intentionally narrow and will later be replaced or migrated when the SQLite persistence work in issue #6 is implemented.

Only the most recent `CHAT_CONTEXT_MESSAGES` messages are retained for prompt context. Credentials and bot tokens are never stored in session files.

## Commands

- `/help` — show transport help.
- `/clear` — remove retained context for the current chat/user session.
- `/approve-sensitive` — approve exactly one sensitive tool call in the next request, valid for `CHAT_SENSITIVE_APPROVAL_TTL_SECONDS` seconds.

A normal sensitive request without that one-shot grant is denied by the existing v0.2 policy. Approval does not change the configured write allowlists and cannot make an ADMIN/unknown tool available.

For example:

1. Send `/approve-sensitive`.
2. Send the sensitive request within the configured TTL.
3. At most one sensitive tool call may consume the grant; further sensitive calls require another approval.

## Operational guardrails

Requests are serialized per conversation to avoid duplicate concurrent responses. A simple per-identity rate limit rejects requests received faster than `CHAT_MIN_INTERVAL_SECONDS`. Telegram update offsets are advanced before processing each update, favoring duplicate prevention over automatic replay after a process crash.
