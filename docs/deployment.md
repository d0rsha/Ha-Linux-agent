# Deployment and automatic updates

This guide is for a permanent HA Linux Agent installation on a Linux server on the same private LAN as Home Assistant.

The deployment is pull-based: the server does not expose SSH, Docker, a webhook, or a GitHub self-hosted runner to the internet. A local systemd timer periodically checks GitHub and GHCR using outbound connections.

## What actually runs the automatic deployment?

The automatic updater is **systemd on the LAN server**. It is not a Docker container and it does not depend on the application containers already being started.

```text
ha-linux-agent-deploy.timer
        ↓ every 5 minutes
ha-linux-agent-deploy.service
        ↓
/opt/ha-linux-agent/deploy/update.sh
        ↓
git fetch/reset origin/main
        ↓
docker compose pull
        ↓
docker compose up -d --no-build
```

You therefore do **not** need to run `docker compose up -d` before enabling deployment. The first run of `ha-linux-agent-deploy.service` starts the selected containers detached. The timer then repeats the same deployment operation every five minutes.

## What happens after a merge to main?

1. GitHub Actions runs tests and the deployment Compose coverage check.
2. If they pass, GitHub Actions builds the HA Linux Agent Docker image.
3. The image is pushed to GHCR as `latest` and as a commit-specific `sha-...` tag.
4. At its next interval, the LAN server's systemd timer runs the deployment service.
5. The deployment script updates the local checkout to `origin/main`.
6. Docker Compose pulls the current images.
7. Docker Compose recreates the configured services when required.

The normal image is:

```text
ghcr.io/d0rsha/ha-linux-agent:latest
```

No inbound deployment connection to the LAN server is required.

## Before you begin

The server needs:

- Git
- Docker Engine
- Docker Compose plugin
- systemd
- outbound HTTPS access to GitHub and GHCR

You also need the normal application secrets and settings that belong in `.env`.

If the GHCR package is public, the server can pull it anonymously. If it remains private, authenticate Docker to `ghcr.io` with package read access before enabling the deployment timer.

## 1. Clone the repository

The supplied systemd unit expects the repository at `/opt/ha-linux-agent`:

```bash
sudo git clone https://github.com/d0rsha/Ha-Linux-agent.git /opt/ha-linux-agent
cd /opt/ha-linux-agent
```

If the repository is already cloned elsewhere, either move/re-clone it to this path or update both the deployment configuration and systemd unit paths consistently.

The deployment script performs `git reset --hard origin/main`. Do not keep local modifications in tracked repository files. Put local secrets and deployment choices in the files described below.

## 2. Configure the application

Create the local `.env`:

```bash
cd /opt/ha-linux-agent
sudo cp .env.example .env
sudo nano .env
```

At minimum, configure the Home Assistant and model settings required by the services you intend to run. Optional integrations such as Telegram and OpenAI Secure MCP Tunnel require their corresponding variables.

`.env` is ignored by Git and remains local when the deployment script resets the repository to `main`.

## 3. Choose which long-running services to deploy

Copy the deployment configuration:

```bash
sudo cp /opt/ha-linux-agent/deploy/ha-linux-agent-deploy.example /etc/default/ha-linux-agent-deploy
sudo nano /etc/default/ha-linux-agent-deploy
```

For an explicit production allowlist, set `DEPLOY_SERVICES`. For example:

```bash
DEPLOY_ROOT=/opt/ha-linux-agent
DEPLOY_BRANCH=main
DEPLOY_SERVICES="ha-agent-telegram openai-mcp-tunnel"
```

This example keeps the Telegram adapter and OpenAI Secure MCP Tunnel running.

If `DEPLOY_SERVICES` is empty, the deployment script runs Compose without an explicit service list. In that mode, unprofiled services are started and optional profiles depend on `COMPOSE_PROFILES`. An explicit `DEPLOY_SERVICES` list is easier to reason about for a permanent server.

Current service roles are defined in `compose.yaml`. Only select services that exist in the current `main` branch and configure any required environment variables first.

## 4. Install the systemd units

```bash
sudo cp /opt/ha-linux-agent/deploy/systemd/ha-linux-agent-deploy.service /etc/systemd/system/
sudo cp /opt/ha-linux-agent/deploy/systemd/ha-linux-agent-deploy.timer /etc/systemd/system/
sudo systemctl daemon-reload
```

At this point **automatic deployment is not enabled yet** and the application containers do not need to be running.

## 5. Run the first deployment manually

Start the one-shot deployment service:

```bash
sudo systemctl start ha-linux-agent-deploy.service
```

This performs the first complete deployment:

```text
git fetch/reset
→ docker compose pull
→ docker compose up -d --no-build
```

It therefore starts the selected containers detached for you.

Check whether it succeeded:

```bash
sudo systemctl status ha-linux-agent-deploy.service
journalctl -u ha-linux-agent-deploy.service --no-pager -n 100
```

Then inspect the containers:

```bash
cd /opt/ha-linux-agent
docker compose -f compose.yaml -f compose.deploy.yaml ps
```

If a service fails, inspect its logs before enabling automatic updates:

```bash
docker compose -f compose.yaml -f compose.deploy.yaml logs --tail=100
```

## 6. Enable automatic deployment

Only after the first deployment works, enable the timer:

```bash
sudo systemctl enable --now ha-linux-agent-deploy.timer
```

This is the command that turns on automatic polling/deployment.

Verify it:

```bash
systemctl status ha-linux-agent-deploy.timer
systemctl list-timers ha-linux-agent-deploy.timer
```

The timer waits two minutes after boot and runs the deployment service every five minutes.

From this point onward, you normally do not need to SSH into the server after merging application changes to `main`.

## 7. Verify an automatic update

After a future merge to `main`, check the deployment history with:

```bash
journalctl -u ha-linux-agent-deploy.service --since "30 minutes ago"
```

Check the running containers with:

```bash
cd /opt/ha-linux-agent
docker compose -f compose.yaml -f compose.deploy.yaml ps
```

The timer is independent of the containers: even if a selected application container is stopped, the next successful deployment run can start it again because the deployment command uses `docker compose up -d`.

## Manual deployment without waiting for the timer

At any time, trigger the same deployment operation manually:

```bash
sudo systemctl start ha-linux-agent-deploy.service
```

Follow it live with:

```bash
journalctl -u ha-linux-agent-deploy.service -f
```

This is preferable to manually reproducing the Git pull and Compose commands because it exercises the same path as the timer.

## GHCR image publishing

The GitHub Actions publish workflow creates:

```text
ghcr.io/d0rsha/ha-linux-agent:latest
ghcr.io/d0rsha/ha-linux-agent:sha-<commit>
```

The `ghcr.io/d0rsha` namespace follows the GitHub account. You do not create that namespace manually. The package is created when the workflow successfully pushes the image for the first time.

For this public repository, making the resulting `ha-linux-agent` container package public allows the LAN server to pull it without storing GitHub registry credentials. If you deliberately keep the package private, authenticate Docker on the server instead.

## Image selection and rollback

The deployment Compose override defaults to:

```text
ghcr.io/d0rsha/ha-linux-agent:latest
```

Each successful publish also creates a commit-specific tag. To pin or roll back, set `HA_AGENT_IMAGE` in the server-local `.env`:

```bash
HA_AGENT_IMAGE=ghcr.io/d0rsha/ha-linux-agent:sha-abc1234
```

Then run:

```bash
sudo systemctl start ha-linux-agent-deploy.service
```

Remove the `HA_AGENT_IMAGE` override to return to `latest`.

## Optional services

### Telegram

Configure `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_USERS` in `.env`, then include:

```bash
ha-agent-telegram
```

in `DEPLOY_SERVICES`.

See [telegram.md](telegram.md) for transport-specific configuration.

### OpenAI Secure MCP Tunnel

Configure `OPENAI_TUNNEL_ID`, `OPENAI_TUNNEL_API_KEY`, `HA_MCP_URL`, and `HA_TOKEN` in `.env`, then include:

```bash
openai-mcp-tunnel
```

in `DEPLOY_SERVICES`.

See [secure-mcp-tunnel.md](secure-mcp-tunnel.md) for tunnel creation and ChatGPT configuration.

### Host MCP

Configure the host MCP settings and include:

```bash
ha-agent-host-mcp
```

in `DEPLOY_SERVICES` when this machine should expose the restricted host diagnostics MCP service.

See [host-mcp.md](host-mcp.md).

## Compose deployment coverage

`compose.yaml` is the source definition for services. `compose.deploy.yaml` overrides locally built HA Linux Agent services so production deployment uses the published GHCR image instead of building source on the LAN server.

Every service in `compose.yaml` that uses `build:` must therefore have a matching `image:` override in `compose.deploy.yaml`.

CI enforces this with:

```bash
python deploy/check_compose_coverage.py
```

A future locally built service cannot be merged cleanly without adding its deployment image override. Services that already use an external image, such as `openai-mcp-tunnel`, do not require an entry in `compose.deploy.yaml`.

## Troubleshooting

### Nothing updates automatically

Check the timer first:

```bash
systemctl status ha-linux-agent-deploy.timer
systemctl list-timers ha-linux-agent-deploy.timer
```

If the timer was never enabled, run:

```bash
sudo systemctl enable --now ha-linux-agent-deploy.timer
```

### The timer runs but deployment fails

Inspect the one-shot service log:

```bash
journalctl -u ha-linux-agent-deploy.service --no-pager -n 200
```

Then test the same operation manually:

```bash
sudo systemctl start ha-linux-agent-deploy.service
sudo systemctl status ha-linux-agent-deploy.service
```

### GHCR pull is denied

If the package is intended to be public, verify the package visibility in GitHub. If it is private, authenticate Docker to GHCR with package read access.

### A container is not started

Check `DEPLOY_SERVICES` in:

```text
/etc/default/ha-linux-agent-deploy
```

Then verify that all environment variables required by that service are present in `/opt/ha-linux-agent/.env`.

## Security boundary

- The LAN server exposes no deployment listener to the internet.
- No self-hosted GitHub runner is installed on the LAN server.
- `.env` remains local and is not committed.
- GitHub Actions publishes the application image with repository-scoped credentials.
- The server executes deployment metadata from trusted `main`; merges to `main` are therefore part of the deployment security boundary.
- Docker itself is privileged infrastructure. Anyone able to change trusted deployment configuration or the published application image can affect what runs on this server.
