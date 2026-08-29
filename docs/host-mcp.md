# Host diagnostics MCP

v0.5 can expose restricted read-only Linux diagnostics from a managed host. The host MCP server is meant for LAN/VPN/Tailscale access and binds to `127.0.0.1` by default.

## Tools

The server exposes only these tools:

- `GetCpu`
- `GetMemory`
- `GetDiskUsage`
- `GetHostUptime`
- `CheckHostReachability`
- `GetServiceStatus`
- `GetDockerContainers`
- `ReadSelectedLogs`

There is no generic shell tool. Service, Docker, log, and reachability tools require explicit allowlists.

## Run on a host

Configure a long random token:

```env
HOST_MCP_TOKEN=replace-with-long-random-token
HOST_MCP_BIND=127.0.0.1
HOST_MCP_PORT=8750
```

Start with Docker Compose:

```bash
docker compose --profile host-mcp up -d ha-agent-host-mcp
```

Or run directly:

```bash
ha-agent host-mcp
```

Expose it only through a trusted private path. Tailscale, WireGuard, or an SSH tunnel are preferred. Do not publish the port directly to the internet.

## Connect from the main agent

On the main HA Linux Agent instance:

```env
HOST_MCP_URLS=http://host-vpn-ip:8750/mcp
HOST_MCP_TOKEN=replace-with-long-random-token
```

The main agent filters remote MCP tools to the known host diagnostic set before showing anything to the model. If a remote server advertises unrelated tools, they are ignored.

## Allowlists

Default local `/proc` tools need no extra permissions:

```env
HOST_DIAGNOSTICS_ENABLED=true
HOST_PROC_ROOT=/proc
HOST_DISK_PATHS=/
```

Enable service status per unit:

```env
HOST_SERVICE_ALLOWLIST=ssh.service,docker.service
```

Enable bounded log reads:

```env
HOST_LOG_PATHS=/var/log
HOST_JOURNAL_UNITS=ssh.service
HOST_LOG_MAX_BYTES=65536
HOST_LOG_MAX_AGE_SECONDS=3600
```

Enable reachability checks per target:

```env
HOST_REACHABILITY_TARGETS=homeassistant.local:8123,router.local:80
HOST_REACHABILITY_TIMEOUT_SECONDS=3
```

Docker status is intentionally opt-in because the Docker socket is powerful:

```env
HOST_DOCKER_SOCKET=/var/run/docker.sock
HOST_DOCKER_ALLOWLIST=homeassistant,mosquitto
```

If you use Docker Compose, mount the socket only for the host MCP service after accepting that risk.

## Low-privilege account

Where practical, run `ha-agent host-mcp` under a dedicated user. Grant only the minimum read access needed for selected logs or systemd status. Avoid adding the user to privileged groups unless the corresponding tool really needs it.

## Direct diagnostics

Run individual tools without the model:

```bash
ha-agent host cpu
ha-agent host memory
ha-agent host disk --path /
ha-agent host uptime
ha-agent host service ssh.service
ha-agent host logs --path /var/log/syslog
```
