# HA Linux Agent

A small, headless AI agent that runs on Linux and uses Home Assistant through its MCP Server integration.

The project supports interactive questions, scheduled reports, persistent chat, Home Assistant history, restricted Linux host diagnostics, and optional private ChatGPT access through OpenAI Secure MCP Tunnel.

## Responsibilities

This repository owns the application:

- Python source and tests
- the application Docker image
- local/manual Docker Compose definitions
- `.env.example` as the application configuration contract
- feature-specific documentation

Production deployment is intentionally outside this repository. A deployment system should consume the published container image and provide its own runtime configuration, secrets, networking, restart policies, and rollout mechanism.

## Quick start

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

## Published container image

Successful `main` builds publish:

```text
ghcr.io/d0rsha/ha-linux-agent:latest
ghcr.io/d0rsha/ha-linux-agent:sha-<commit>
```

`latest` is convenient for continuously deployed environments. The commit-specific tag is suitable for pinning and rollback. See **[docs/container-image.md](docs/container-image.md)**.

The repository's `compose.yaml` is primarily for local/manual operation. Production infrastructure should reference the published image directly rather than depending on deployment files from this repository.

## Configuration contract

`.env.example` documents the variables understood by the application and optional services. New required configuration should be added there in the same change that introduces it.

A production deployment may keep non-secret configuration in its own private repository and inject secrets from its deployment secret store.

## Architecture

The agent uses:

- **Home Assistant MCP** for live context and policy-controlled actions.
- **Home Assistant REST/WebSocket APIs** for read-only historical data and report notification delivery.
- **Restricted host diagnostics** for read-only Linux CPU, memory, disk, service, Docker, log, uptime, and reachability evidence.
- **External scheduling** for deterministic report runs.
- **Transport-independent chat services**, with Telegram as the first adapter.
- **Optional OpenAI Secure MCP Tunnel** for private ChatGPT access to the Home Assistant MCP endpoint without public ingress.

Historical access never opens `home-assistant_v2.db` directly. InfluxDB and Grafana are not required.

## Security model

There are independent permission boundaries:

1. **Home Assistant MCP** controls what is exposed and whether Home Assistant control is enabled.
2. **Host diagnostics MCP** exposes only a narrow read-only host tool set.
3. **HA Linux Agent policy** filters which tools the model can see and authorizes every tool call before execution.

Unknown MCP tools are blocked by default. Administrative tools are prohibited. Sensitive writes require explicit confirmation. Scheduled reports are forcibly read-only even if interactive/chat writes are enabled.

All tool output is treated as untrusted data before it is returned to the model. Secrets are redacted from model-visible tool output and audit logs.

See **[docs/security.md](docs/security.md)** for the full security model.

## Home Assistant historical analysis

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

## Host diagnostics

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

## Scheduled reports

Run a report manually:

```bash
docker compose run --rm -T ha-agent report
```

Configure Home Assistant delivery with `REPORT_NOTIFY_SERVICE`. See **[docs/scheduling.md](docs/scheduling.md)**.

## Telegram persistent chat

Configure `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_USERS`, then run locally with:

```bash
docker compose --profile telegram up -d ha-agent-telegram
```

See **[docs/telegram.md](docs/telegram.md)**.

## OpenAI Secure MCP Tunnel

The optional tunnel forwards ChatGPT MCP requests to a private Home Assistant MCP endpoint. `HA_TOKEN` remains on the machine running the tunnel and is sent as the MCP Authorization bearer header.

For local Compose operation:

```bash
docker compose --profile secure-mcp-tunnel up -d openai-mcp-tunnel
```

See **[docs/secure-mcp-tunnel.md](docs/secure-mcp-tunnel.md)**.

## Persistent memory and audit data

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

- **[Container image](docs/container-image.md)** — GHCR tags and the production-consumer contract.
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
```

GitHub Actions runs the test suite for pushes and pull requests. Successful `main` builds publish the application image to GHCR.
