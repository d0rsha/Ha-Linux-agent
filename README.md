# HA Linux Agent v0.4

A small, headless AI agent that runs on a Linux server and uses Home Assistant through its MCP Server integration.

v0.4 builds on v0.3 native Home Assistant historical analysis with scheduled house-health reports and a persistent remote chat transport.

## Architecture

The agent uses:

- **Home Assistant MCP** for live context and policy-controlled actions.
- **Home Assistant REST/WebSocket APIs** for read-only historical data and report notification delivery.
- **External scheduling** (systemd/cron) for deterministic report runs.
- **Transport-independent chat services**, with Telegram as the first adapter.

Historical access never opens `home-assistant_v2.db` directly. InfluxDB and Grafana are not required.

## Security model

There are two independent boundaries:

1. **Home Assistant MCP** controls what is exposed and whether Home Assistant control is enabled.
2. **HA Linux Agent policy** filters which tools the model can see and authorizes every tool call before execution.

Unknown MCP tools are blocked by default. Administrative tools are prohibited. Sensitive writes require explicit confirmation.

Scheduled reports are forcibly read-only even if interactive/chat writes are enabled.

The local historical tools are read-only:

- `GetHistory` — recent Recorder state history.
- `ListStatistics` — discover long-term statistic IDs.
- `GetStatistics` — query bounded long-term statistics.

## Linux deployment

Requirements: Docker Engine + Docker Compose plugin.

```bash
cp .env.example .env
nano .env

docker compose build
```

Inspect tools/policy:

```bash
docker compose run --rm ha-agent tools
```

Ask a question:

```bash
docker compose run --rm ha-agent ask "How has indoor temperature changed over the last week?"
```

## Home Assistant historical analysis

v0.3 history remains enabled by default:

```env
HA_HISTORY_ENABLED=true
HA_HISTORY_MAX_ENTITIES=5
HA_HISTORY_MAX_DAYS=14
HA_STATISTICS_MAX_DAYS=3650
HA_HISTORY_MAX_POINTS=2000
```

`HA_BASE_URL` normally does not need to be set. It is derived from `HA_MCP_URL`.

Direct diagnostics:

```bash
docker compose run --rm ha-agent statistics-list --query temperature

docker compose run --rm ha-agent history sensor.example \
  --start 2026-08-28T00:00:00+02:00 \
  --end 2026-08-29T00:00:00+02:00

docker compose run --rm ha-agent statistics sensor.example \
  --start 2026-08-01T00:00:00+02:00 \
  --end 2026-08-29T00:00:00+02:00 \
  --period day
```

Missing or purged data is treated as missing data, not evidence that an event did not occur.

## Scheduled reports

The report prompt is separate from Python source at `prompts/house_health.md`.

Run manually:

```bash
docker compose run --rm -T ha-agent report
```

Configure Home Assistant delivery:

```env
REPORT_NOTIFY_SERVICE=ALL_DEVICES
```

Leave `REPORT_NOTIFY_SERVICE` blank for stdout only.

Anomaly-only mode suppresses delivery when no meaningful condition is found:

```bash
docker compose run --rm -T ha-agent report --anomalies-only
```

Reports have timeout/retry limits and use a shared `/data/report.lock` to prevent overlapping container runs. See [`docs/scheduling.md`](docs/scheduling.md) for a systemd timer example.

## Telegram persistent chat

Configure an explicit bot token and numeric user allowlist:

```env
TELEGRAM_BOT_TOKEN=123456:replace-me
TELEGRAM_ALLOWED_USERS=123456789
```

Start it:

```bash
docker compose --profile telegram up -d ha-agent-telegram
```

The transport keeps bounded conversation context in the persistent `ha-agent-data` volume, serializes requests per session, and rate-limits inbound users.

Sensitive actions still use the existing policy. Telegram requires a one-request, one-sensitive-call grant:

1. Send `/approve-sensitive`.
2. Send the sensitive request before the short TTL expires.
3. The grant expires after that request whether it is used or not.

`/clear` clears retained chat context. Unknown Telegram users are ignored before model invocation. See [`docs/telegram.md`](docs/telegram.md).

The v0.4 JSON session store is intentionally narrow; SQLite conversation/memory/audit persistence remains tracked separately in issue #6.

## LLM providers

OpenAI:

```env
LLM_PROVIDER=openai
LLM_MODEL=gpt-5.4-mini
LLM_API_KEY=...
```

OpenRouter:

```env
LLM_PROVIDER=openrouter
LLM_MODEL=openai/gpt-5.2
LLM_API_KEY=sk-or-v1-...
```

Generic OpenAI-compatible endpoint:

```env
LLM_PROVIDER=openai-compatible
LLM_MODEL=my-tool-capable-model
LLM_API_KEY=local-or-provider-key
LLM_BASE_URL=http://192.168.1.10:8080/v1
```

## Home Assistant writes

Do not grant every write tool. Enable **Control Home Assistant** in HA MCP first, inspect the tools, then allow-list exact write tools in `.env`.

Permission tiers:

- `READ`: allowed automatically.
- `SAFE_WRITE`: allowed only when writes are enabled and the exact tool is allow-listed.
- `SENSITIVE_WRITE`: requires explicit confirmation.
- `ADMIN`: denied.

## Development

```bash
python -m pip install -e '.[dev]'
pytest -q
```

GitHub Actions runs the same suite for pushes and pull requests.

## Next versions

- SQLite conversation, memory, and persistent audit history (#6).
- Optional InfluxDB historical backend if it proves useful (#12).
- Restricted Linux/PC MCP diagnostics and broader security hardening.
