# Signal persistent chat

HA Linux Agent uses a separate `signal-cli-rest-api` service as its Signal client. Signal messages remain end-to-end encrypted on the Signal network, but plaintext is necessarily available inside the trusted bridge/agent deployment boundary.

## Configure

Set the agent environment:

```env
SIGNAL_API_URL=http://signal-api:8080
SIGNAL_NUMBER=+46000000000
SIGNAL_ALLOWED_SENDERS=+46000000001
```

Use international E.164-style phone numbers. `SIGNAL_ALLOWED_SENDERS` is mandatory and can contain multiple comma-separated senders.

## Register or link Signal

The Signal account must be registered or linked in the `signal-api` container before starting the agent transport. The bridge persists Signal account state in the `signal-cli-data` Docker volume.

Follow the bridge's registration/linking procedure for the installed image version. Do not commit Signal account state, verification codes, or credentials.

## Start

```bash
docker compose --profile signal up -d signal-api
# Register/link the configured SIGNAL_NUMBER using the bridge.
docker compose --profile signal up -d ha-agent-signal
```

The agent polls the bridge for incoming messages and sends replies through `/v2/send`.

## Commands

- `/help` — show chat usage.
- `/clear` — clear retained conversation context.
- `/approve-sensitive` — approve one sensitive action for the next request within the configured TTL.

Unknown Signal senders are ignored before model invocation.

## Security

- Keep `signal-api` on the private Compose network; do not publish its port by default.
- Treat the Signal client state volume as sensitive because the bridge terminates Signal encryption.
- Keep sender allowlists narrow.
- If you expose the REST bridge outside the private host/network, put authentication and TLS in front of it.
- Normal agent write-policy and sensitive-action confirmation rules still apply.
