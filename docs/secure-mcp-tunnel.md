# OpenAI Secure MCP Tunnel

This optional Compose profile exposes the existing private Home Assistant MCP server to ChatGPT through OpenAI Secure MCP Tunnel without opening an inbound port or bypassing an existing Cloudflare Access setup.

## Architecture

```text
ChatGPT
  -> OpenAI-hosted tunnel endpoint
  <- outbound HTTPS from tunnel-client
  -> Home Assistant LAN endpoint (/api/mcp/assist)
```

`tunnel-client` runs on the same Linux host as HA Linux Agent. It needs outbound HTTPS access to `api.openai.com:443` and LAN access to `HA_MCP_URL`. Home Assistant remains private.

## Credentials

Three values are involved:

- `OPENAI_TUNNEL_ID` identifies the tunnel created in OpenAI Platform.
- `OPENAI_TUNNEL_API_KEY` is the runtime API key used by `tunnel-client`. It is not an OpenAI admin key.
- `HA_TOKEN` is the existing Home Assistant long-lived access token. Compose injects it as the `Authorization: Bearer ...` header only on requests to the configured MCP server.

Keep all three in `.env`, which is ignored by Git. Do not commit real credentials.

For least privilege, create the Home Assistant token for a dedicated non-admin Home Assistant user and restrict which entities are exposed through Home Assistant Assist/MCP.

## Configure

Create a Secure MCP Tunnel in OpenAI Platform and associate it with the ChatGPT workspace that will use it. Add the resulting values to `.env`:

```env
HA_MCP_URL=http://192.168.x.x:8123/api/mcp/assist
HA_TOKEN=replace-with-a-dedicated-home-assistant-long-lived-token
OPENAI_TUNNEL_ID=tunnel_0123456789abcdef0123456789abcdef
OPENAI_TUNNEL_API_KEY=sk-replace-with-runtime-api-key
```

The tunnel container reuses `HA_MCP_URL` and `HA_TOKEN`; there is no second copy of the Home Assistant credential in ChatGPT.

## Start

Pull and start only the tunnel profile:

```bash
docker compose --profile secure-mcp-tunnel pull openai-mcp-tunnel
docker compose --profile secure-mcp-tunnel up -d openai-mcp-tunnel
docker compose logs -f openai-mcp-tunnel
```

The service uses host networking so the same LAN/local Home Assistant address used by HA Linux Agent is reachable from `tunnel-client`.

## Validate

The official client provides `doctor`. Run it with the same environment as the Compose service:

```bash
docker compose --profile secure-mcp-tunnel run --rm openai-mcp-tunnel doctor --explain
```

If validation succeeds, keep the service running while connecting ChatGPT.

## Connect ChatGPT

In ChatGPT developer mode, create an app and choose **Tunnel** as the connection type. Select the tunnel associated with the intended ChatGPT workspace, or enter its tunnel ID.

Do not enter the Home Assistant LAN URL or long-lived token in ChatGPT. The LAN URL and bearer token are consumed locally by `tunnel-client`.

## Security notes

- The tunnel is outbound-only; no Home Assistant or tunnel-client inbound internet port is required.
- The Home Assistant token remains in the local `.env` file and process environment on this Docker host.
- `MCP_EXTRA_HEADERS` is scoped by tunnel-client to outbound traffic for the configured MCP server origin.
- Keep the Home Assistant MCP exposure narrow. Avoid exposing locks, alarm controls, cameras, location/person entities, or administrative tools unless explicitly required.
- Rotate `HA_TOKEN` and `OPENAI_TUNNEL_API_KEY` if the Docker host or `.env` is compromised.

## References

- OpenAI Secure MCP Tunnel: https://developers.openai.com/api/docs/guides/secure-mcp-tunnels
- tunnel-client configuration: https://github.com/openai/tunnel-client/blob/master/docs/configuration.md
- Home Assistant MCP Server: https://www.home-assistant.io/integrations/mcp_server/
