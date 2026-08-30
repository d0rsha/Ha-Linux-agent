# HA Linux Agent

A small, headless AI agent that runs on a Linux server and uses Home Assistant through its MCP Server integration.

The project supports interactive questions, scheduled reports, persistent chat, Home Assistant history, restricted Linux host diagnostics, and optional private ChatGPT access through OpenAI Secure MCP Tunnel.

## Start here

There are two different ways to run the project. Choose the one that matches what you are doing:

- **Local/manual use** — build from the checked-out source and run commands with Docker Compose. Use this for development and ad-hoc CLI questions.
- **Always-on server deployment** — run selected services in the background and let a systemd timer automatically pull new `main` revisions and GHCR images. Use this for a LAN server that should update itself after merges.

For a permanent server installation, follow **[docs/deployment.md](docs/deployment.md)**. You do **not** need to manually start the containers before enabling automatic deployment; the deployment service performs the first `docker compose up -d` for you.

## Architecture

The agent uses:

- **Home Assistant MCP** for live context and policy-controlled actions.
- **Home Assistant REST/WebSocket APIs** for read-only historical data and report notification delivery.
- **Restricted host diagnostics** for read-only Linux CPU, memory, disk, service, Docker, log, uptime, and reachability evidence.
- **External scheduling** (systemd/cron) for deterministic report runs.
- **Transport-independent chat services**, with Telegram as the first adapter.
- **Optional OpenAI Secure MCP Tunnel** for private ChatGPT access to the Home Assistant MCP endpoint without public ingress.

Historical access never opens `home-assistant_v2.db` directly. InfluxDB and Grafana are not required.

## Quick start: local/manual use

Requirements: Docker Engine + Docker Compose plugin.

```bash
git clone https://github.com/d0rsha/Ha-Linux-agent.git
cd Ha-Linux-agent
cp .env.example .env
nano .env
docker compose build
```

Inspect tools and policy:

```bash
docker compose run --rm ha-agent tools
```

Ask a question:

```bash
docker compose run --rm ha-agent ask "How has indoor temperature changed over the last week?"
```

These commands are one-shot containers. They do not enable automatic deployment and do not need to remain running.

## Permanent server deployment and automatic updates

For an always-on LAN server, the repository contains a separate pull-based deployment path:

```text
merge to main
    ↓
GitHub Actions: tests + Docker build
    ↓
GHCR: ghcr.io/d0rsha/ha-linux-agent:latest
    ↓
LAN server systemd timer (every 5 minutes)
    ↓
git fetch/reset + docker compose pull + docker compose up -d
```

The **systemd timer**, not an already-running container, triggers automatic updates. The first manual start of `ha-linux-agent-deploy.service` pulls the current images and starts the configured services detached. After that, `ha-linux-agent-deploy.timer` checks for updates every five minutes.

Complete installation, service selection, first deployment, timer activation, verification, GHCR visibility, and rollback instructions are in **[docs/deployment.md](docs/deployment.md)**.

## Security model

There are independent permission boundaries:

1. **Home Assistant MCP** controls what is exposed and whether Home Assistant control is enabled.
2. **Host diagnostics MCP** exposes only a narrow read-only host tool set.
3. **HA Linux Agent policy** filters which tools the model can see and authorizes every tool call before execution.

Unknown MCP tools are blocked by default. Administrative tools are prohibited. Sensitive writes require explicit confirmation. Scheduled reports are forcibly read-only even if interactive/chat writes are enabled.

All tool output is treated as untrusted data before it is returned to the model. Secrets are redacted from model-visible tool output and audit logs. Each agent request receives a correlation ID, and `AUDIT_LOG_PATH` can enable a persistent JSONL audit trail.

See **[docs/security.md](docs/security.md)** for the full security model.

## Features and configuration

### Home Assistant historical analysis

History is enabled by default:

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
docker compose run --rm ha-agent history sensor.example --start 2026-08-28T00:00:00+02:00 --end 2026-08-29T00:00:00+02:00
docker compose run --rm ha-agent statistics sensor.example --start 2026-08-01T00:00:00+02:00 --end 2026-08-29T00:00:00+02:00 --period day
```

Missing or purged data is treated as missing data, not evidence that an event did not occur.

### Host diagnostics

Cheap local `/proc` diagnostics are enabled by default:

```env
HOST_DIAGNOSTICS_ENABLED=true
HOST_PROC_ROOT=/proc
HOST_DISK_PATHS=/
```

Direct checks:

```bash
docker compose run --rm ha-agent host cpu
docker compose run --rm ha-agent host memory
docker compose run --rm ha-agent host disk --path /
docker compose run --rm ha-agent host uptime
```

Higher-risk surfaces require explicit allowlists. See **[docs/host-mcp.md](docs/host-mcp.md)**.

### Scheduled reports

Run a report manually:

```bash
docker compose run --rm -T ha-agent report
```

Configure Home Assistant delivery with `REPORT_NOTIFY_SERVICE`. See **[docs/scheduling.md](docs/scheduling.md)** for report scheduling.

### Telegram persistent chat

Configure `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_USERS`, then run the Telegram service manually with:

```bash
docker compose --profile telegram up -d ha-agent-telegram
```

For a permanent auto-updating deployment, select `ha-agent-telegram` through the deployment configuration instead of maintaining a separate manual Compose process. See **[docs/telegram.md](docs/telegram.md)**.

### OpenAI Secure MCP Tunnel

The optional tunnel forwards ChatGPT MCP requests to the private Home Assistant MCP endpoint. `HA_TOKEN` remains on the LAN server and is sent as the MCP Authorization bearer header.

For manual Compose operation:

```bash
docker compose --profile secure-mcp-tunnel up -d openai-mcp-tunnel
```

For a permanent auto-updating deployment, select `openai-mcp-tunnel` in the deployment configuration. See **[docs/secure-mcp-tunnel.md](docs/secure-mcp-tunnel.md)**.

### Persistent memory and audit data

Conversation, memory, and tool-call audit state can be persisted in SQLite under the shared data volume. See **[docs/memory.md](docs/memory.md)**.

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

The Codex CLI can also be used as a backend; see **[docs/codex-cli-backend.md](docs/codex-cli-backend.md)**.

## Home Assistant writes

Do not grant every write tool. Enable **Control Home Assistant** in HA MCP first, inspect the tools, then allow-list exact write tools in `.env`.

Permission tiers:

- `READ`: allowed automatically.
- `SAFE_WRITE`: allowed only when writes are enabled and the exact tool is allow-listed.
- `SENSITIVE_WRITE`: requires explicit confirmation.
- `ADMIN`: denied.

## Documentation

- **[Deployment and automatic updates](docs/deployment.md)** — production/LAN installation, GHCR, systemd timer, service selection, rollback.
- **[Security](docs/security.md)** — policy boundaries, writes, secrets, audit handling.
- **[OpenAI Secure MCP Tunnel](docs/secure-mcp-tunnel.md)** — private ChatGPT-to-Home-Assistant MCP access.
- **[Host MCP](docs/host-mcp.md)** — restricted diagnostics for Linux hosts.
- **[Telegram](docs/telegram.md)** — persistent Telegram chat transport.
- **[Scheduling](docs/scheduling.md)** — scheduled reports.
- **[Memory](docs/memory.md)** — SQLite conversation, memory, and audit persistence.
- **[Codex CLI backend](docs/codex-cli-backend.md)** — using Codex CLI as the model backend.

## Development

```bash
python -m pip install -e '.[dev]'
pytest -q
python deploy/check_compose_coverage.py
```

GitHub Actions runs the test suite and deployment Compose coverage checks for pushes and pull requests.
