# HA Linux Agent v0.1

A deliberately small, headless AI agent that runs on a Linux server and reads live Home Assistant context through Home Assistant's MCP Server integration.

## Security model for v0.1

1. In Home Assistant, add **Model Context Protocol Server**.
2. Keep **Control Home Assistant** disabled.
3. Expose only entities you want the agent to read.
4. Create a dedicated non-admin Home Assistant user for the agent where practical.
5. Create a long-lived access token for that user.
6. Use the Assist endpoint: `/api/mcp/assist`.
7. Keep the MCP connection on LAN/VPN; do not publish it just for this agent.

Home Assistant's MCP integration determines the real authorization boundary. The Python agent does not attempt to infer which MCP tools are safe.

## Linux deployment

Requirements: Docker Engine + Docker Compose plugin.

```bash
cp .env.example .env
nano .env

docker compose build
```

Check the connection and see what HA exposes:

```bash
docker compose run --rm ha-agent tools
```

Ask a question:

```bash
docker compose run --rm ha-agent ask "Give me a status report for the house"
```

Other useful first prompts:

```bash
docker compose run --rm ha-agent ask "Are any servers or important devices unhealthy?"
docker compose run --rm ha-agent ask "How warm is the house compared with outside?"
docker compose run --rm ha-agent ask "What does the current electricity situation look like?"
```

## Why `network_mode: host`?

For a trusted Linux server on your LAN it avoids Docker DNS/routing surprises when Home Assistant is addressed by a local IP or `.local` hostname. If you prefer normal Docker networking and your HA URL is routable from the container, remove `network_mode: host`.

## v0.2

Add selected write actions by enabling Home Assistant control only after reviewing the exposed entities and the tools returned by `ha-agent tools`. Add an application-side approval policy before exposing sensitive entities such as locks, alarms, doors, or garage controls.

## v0.3+

- SQLite conversation/audit history
- scheduled house-health report
- Telegram or Home Assistant notification ingress/egress
- InfluxDB read tool for historical analysis
- a separate Linux/PC MCP server for Docker, logs, system metrics and restricted administration
