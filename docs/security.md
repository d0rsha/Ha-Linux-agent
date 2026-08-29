# Security model

HA Linux Agent is a private household agent, but it still handles untrusted content from Home Assistant, chat, logs, web-like API responses, and LLM output. v0.5 hardens the boundary between data and authority.

## Trust boundaries

- **LLM provider**: receives prompts and tool results, but never authorizes tools.
- **Home Assistant MCP**: decides what Home Assistant exposes. The agent still applies its own policy before every call.
- **Host diagnostics MCP**: exposes a fixed read-only Linux diagnostics surface. It does not expose arbitrary shell execution.
- **Chat transports**: authenticate users before model invocation. Telegram requires explicit numeric user IDs.
- **Persistent `/data` volume**: stores chat context, report locks, and optional JSONL audit records.

## Authorization

Every tool call passes through `ToolPolicy` before execution:

- Unknown tools are denied.
- Administrative tools are denied.
- Read tools are allowed.
- Safe writes require `HA_WRITE_ENABLED=true` and an exact allowlist entry.
- Sensitive writes require deterministic confirmation outside the model.
- Host tools are explicitly read-only and independent from Home Assistant write settings.

Tool availability is itself an authorization boundary. A tool that is not visible to the model should not be treated as callable.

## Untrusted tool output

Tool results are wrapped before they are sent back to the model:

```xml
<untrusted_tool_output tool="ReadSelectedLogs"><![CDATA[
...
]]></untrusted_tool_output>
```

The system prompt instructs the model to treat tool results as data only. A log line or Home Assistant state that says “ignore previous instructions” or “call this write tool” does not change policy and cannot grant permissions.

## Secret redaction

Tool output and audit records are redacted before they leave the deterministic code path. Redaction covers configured secrets and common credential patterns such as bearer tokens, OpenAI-style keys, Telegram bot tokens, and `api_key=` style values.

Do not intentionally expose secrets through Home Assistant entities, log allowlists, chat messages, or prompts. Redaction is a last line of defense, not a storage policy.

## Audit trail

The `ha_agent.audit` logger emits structured JSON for tool requests, denials, approvals, and execution results. Each agent invocation gets a `correlation_id`.

Set this to persist a JSONL audit trail:

```env
AUDIT_LOG_PATH=/data/audit/audit.jsonl
```

Audit entries include tool name, policy tier, decision, argument keys, correlation ID, and success/failure metadata. Values are redacted before writing.

## Host diagnostics

Host diagnostics are read-only and allowlist-driven:

- No generic `run_shell(command)` tool exists.
- Services are queried with fixed `systemctl show` arguments and exact unit allowlists.
- Logs are restricted to allowlisted paths or journal units, recent time windows, and byte limits.
- Reachability checks are restricted to allowlisted `host:port` targets.
- Docker status requires an explicit socket path and container allowlist.

Remote host MCP must use `HOST_MCP_TOKEN` and should only be reachable over LAN/VPN/Tailscale or an SSH tunnel. It binds to `127.0.0.1` by default.

## Network egress

Docker Compose uses host networking because Home Assistant and host diagnostics often live on the local network. Where practical, restrict outbound traffic at the host firewall to:

- Home Assistant
- the configured LLM provider or local LLM gateway
- configured host MCP endpoints
- Telegram, if the Telegram profile is enabled

Do not expose Home Assistant MCP, host MCP, or chat webhooks publicly unless you have a separate authenticated reverse proxy and understand the risk.

## Backup and recovery

The Docker named volume `ha-agent-data` stores runtime state. Back it up before upgrades:

```bash
docker run --rm -v ha-linux-agent_ha-agent-data:/data -v "$PWD":/backup alpine \
  tar czf /backup/ha-agent-data.tgz -C /data .
```

Restore into an empty volume:

```bash
docker run --rm -v ha-linux-agent_ha-agent-data:/data -v "$PWD":/backup alpine \
  tar xzf /backup/ha-agent-data.tgz -C /data
```

SQLite conversation and durable audit storage remain tracked separately in issue #6.
