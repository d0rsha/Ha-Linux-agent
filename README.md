# HA Linux Agent v0.3

A small, headless AI agent that runs on a Linux server and uses Home Assistant through its MCP Server integration.

v0.3 adds read-only historical analysis using Home Assistant's native Recorder history and long-term statistics. InfluxDB is not required.

## Architecture

The agent uses two Home Assistant interfaces:

- **MCP** for live Home Assistant context and allowed control actions.
- **Home Assistant REST/WebSocket APIs** for read-only historical data.

Historical access never opens `home-assistant_v2.db` directly and does not expose SQL to the model.

## Security model

There are two independent boundaries:

1. **Home Assistant MCP** controls what is exposed and whether Home Assistant control is enabled.
2. **HA Linux Agent policy** filters which tools the model can see and authorizes every tool call before execution.

Unknown MCP tools are blocked by default. Administrative tools are prohibited. Sensitive writes require explicit confirmation.

The local historical tools are read-only:

- `GetHistory` — recent Recorder state history.
- `ListStatistics` — discover long-term statistic IDs.
- `GetStatistics` — query bounded long-term statistics.

For a read-only installation, keep Home Assistant **Control Home Assistant** disabled and leave `HA_WRITE_ENABLED=false`.

## Home Assistant setup

1. Add **Model Context Protocol Server** in Home Assistant.
2. Expose only the entities the agent needs.
3. Prefer a dedicated non-admin Home Assistant user where practical.
4. Create a long-lived access token for that user.
5. Use the Assist endpoint: `/api/mcp/assist`.
6. Keep the connection on LAN/VPN.

The same Home Assistant token is used for the read-only REST/WebSocket history APIs.

## Linux deployment

Requirements: Docker Engine + Docker Compose plugin.

```bash
cp .env.example .env
nano .env

docker compose build
```

Inspect all MCP/local tools and the local authorization policy:

```bash
docker compose run --rm ha-agent tools
```

Ask a historical question:

```bash
docker compose run --rm ha-agent ask "How has indoor temperature changed over the last week?"
```

## Historical analysis

Historical access is enabled by default:

```env
HA_HISTORY_ENABLED=true
HA_HISTORY_MAX_ENTITIES=5
HA_HISTORY_MAX_DAYS=14
HA_STATISTICS_MAX_DAYS=3650
HA_HISTORY_MAX_POINTS=2000
```

`HA_BASE_URL` normally does not need to be set. It is derived from `HA_MCP_URL`. Set it only if REST/WebSocket access uses a different Home Assistant URL.

### Recent Recorder history

`GetHistory` uses Home Assistant's `/api/history/period` REST endpoint with minimal responses and no attributes to keep result size small.

Test it without involving the LLM:

```bash
docker compose run --rm ha-agent history sensor.example \
  --start 2026-08-28T00:00:00+02:00 \
  --end 2026-08-29T00:00:00+02:00
```

Raw history is intentionally range-limited.

### Long-term statistics

Home Assistant long-term statistics are accessed through the Recorder WebSocket API.

Discover available statistic IDs:

```bash
docker compose run --rm ha-agent statistics-list --query temperature
docker compose run --rm ha-agent statistics-list --type sum --query energy
```

Query statistics:

```bash
docker compose run --rm ha-agent statistics sensor.example \
  --start 2026-08-01T00:00:00+02:00 \
  --end 2026-08-29T00:00:00+02:00 \
  --period day
```

Supported periods are `5minute`, `hour`, `day`, `week`, `month`, and `year`. Detailed periods over large ranges are rejected before the request is sent to Home Assistant.

Not every entity has long-term statistics. Missing or purged data is treated as missing data; the agent is instructed not to invent historical values or interpret missing history as proof an event did not occur.

### Why Home Assistant native history first?

v0.3 intentionally does not require InfluxDB or Grafana. Home Assistant already stores recent Recorder history and long-term statistics for eligible sensors. An optional InfluxDB backend can be added later if higher-resolution long-term retention proves useful.

## LLM providers

### OpenAI

```env
LLM_PROVIDER=openai
LLM_MODEL=gpt-5.4-mini
LLM_API_KEY=...
```

The v0.1 variables `OPENAI_API_KEY` and `OPENAI_MODEL` remain supported.

### OpenRouter

```env
LLM_PROVIDER=openrouter
LLM_MODEL=openai/gpt-5.2
LLM_API_KEY=sk-or-v1-...
```

`OPENROUTER_API_KEY` may be used instead of `LLM_API_KEY`.

### Generic OpenAI-compatible endpoint

```env
LLM_PROVIDER=openai-compatible
LLM_MODEL=my-tool-capable-model
LLM_API_KEY=local-or-provider-key
LLM_BASE_URL=http://192.168.1.10:8080/v1
```

Generic compatible endpoints default to `chat_completions`. Set `LLM_API_STYLE=responses` when the endpoint supports the Responses API.

## Enabling selected Home Assistant writes

Do not start by granting every write tool. Enable **Control Home Assistant** in HA MCP first, inspect the tools, then allow-list exact write tools in `.env`.

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

GitHub Actions runs the same test suite for pushes and pull requests.

## Next versions

- SQLite conversation, memory, and persistent audit history.
- Scheduled house-health reports and persistent chat ingress/egress.
- Optional InfluxDB historical backend if it proves useful.
- Restricted Linux/PC MCP diagnostics and broader security hardening.
