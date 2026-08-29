# HA Linux Agent v0.2

A small, headless AI agent that runs on a Linux server and uses Home Assistant through its MCP Server integration.

v0.2 adds pluggable LLM providers and an application-side authorization layer for Home Assistant tools.

## Security model

There are two independent boundaries:

1. **Home Assistant MCP** controls what is exposed and whether Home Assistant control is enabled.
2. **HA Linux Agent policy** filters which MCP tools the model can see and authorizes every tool call before execution.

Unknown MCP tools are blocked by default. Administrative tools are prohibited. Sensitive writes require explicit confirmation.

For a read-only installation, keep Home Assistant **Control Home Assistant** disabled and leave `HA_WRITE_ENABLED=false`.

## Home Assistant setup

1. Add **Model Context Protocol Server** in Home Assistant.
2. Expose only the entities the agent needs.
3. Prefer a dedicated non-admin Home Assistant user where practical.
4. Create a long-lived access token for that user.
5. Use the Assist endpoint: `/api/mcp/assist`.
6. Keep the connection on LAN/VPN.

## Linux deployment

Requirements: Docker Engine + Docker Compose plugin.

```bash
cp .env.example .env
nano .env

docker compose build
```

Inspect the MCP tools and local policy:

```bash
docker compose run --rm ha-agent tools
```

Ask a question:

```bash
docker compose run --rm ha-agent ask "Give me a status report for the house"
```

Show the resolved provider without exposing the key:

```bash
docker compose run --rm ha-agent provider
```

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

OpenRouter defaults to its OpenAI-compatible `/api/v1` base URL and the Responses API style. Model capability varies; choose a model with tool calling support.

### Generic OpenAI-compatible endpoint

```env
LLM_PROVIDER=openai-compatible
LLM_MODEL=my-tool-capable-model
LLM_API_KEY=local-or-provider-key
LLM_BASE_URL=http://192.168.1.10:8080/v1
```

Generic compatible endpoints default to `chat_completions`, because that API is implemented more widely. Override when the server supports the Responses API:

```env
LLM_API_STYLE=responses
```

## Enabling selected Home Assistant writes

Do not start by granting every write tool.

First enable **Control Home Assistant** in HA MCP, then inspect what your instance exposes:

```bash
docker compose run --rm ha-agent tools
```

Configure exact tool names in `.env`, for example:

```env
HA_WRITE_ENABLED=true
HA_SAFE_WRITE_TOOLS=HassTurnOn,HassTurnOff,HassLightSet
HA_SENSITIVE_WRITE_TOOLS=
```

Only read tools plus exact configured write tools are sent to the LLM. An unexpected/new MCP tool therefore does not automatically gain access.

A tool in `HA_SAFE_WRITE_TOOLS` is elevated to `SENSITIVE_WRITE` when its arguments appear to target configured sensitive domains/names:

```env
HA_SENSITIVE_DOMAINS=lock,alarm_control_panel
HA_SENSITIVE_NAME_TERMS=lock,alarm,garage,front door,back door
```

Sensitive calls prompt for confirmation in the CLI. For an explicitly approved one-shot invocation you can use:

```bash
docker compose run --rm ha-agent ask --yes-sensitive "Lock the front door"
```

Use `--yes-sensitive` carefully: it approves sensitive calls made during that invocation. Interactive confirmation is safer.

### Permission tiers

- `READ`: allowed automatically.
- `SAFE_WRITE`: allowed only when writes are enabled and the exact tool is allow-listed.
- `SENSITIVE_WRITE`: requires explicit confirmation.
- `ADMIN`: denied.

Tool requests/executions are written as structured audit log lines to stderr. v0.3 will persist these to SQLite.

## Codex CLI

Codex CLI is intentionally **not** implemented as a drop-in LLM provider in v0.2. It is an agent harness with its own execution/tool model, and on this deployment it lives on the host rather than in the HA agent container. See [`docs/codex-cli-backend.md`](docs/codex-cli-backend.md) for the decision and safe future delegation design.

## Development

```bash
python -m pip install -e '.[dev]'
pytest -q
```

GitHub Actions runs the same test suite for pushes and pull requests.

## Why `network_mode: host`?

For a trusted Linux server on your LAN it avoids Docker DNS/routing surprises when Home Assistant is addressed by a local IP or `.local` hostname. If your HA URL is routable with normal Docker networking, remove `network_mode: host`.

## Next versions

- v0.3: SQLite conversation/audit history and InfluxDB historical analysis.
- v0.4: scheduled house-health reports and persistent chat ingress/egress.
- v0.5: restricted Linux/PC MCP diagnostics and broader security hardening.
