# Pull-based deployment from GitHub and GHCR

This deployment model keeps the Linux server private on the LAN. It does not run a GitHub self-hosted runner and does not expose SSH, Docker, or a webhook endpoint to the internet.

The flow is:

1. A change is merged to `main`.
2. GitHub Actions runs the test suite.
3. If tests pass, GitHub Actions builds the Docker image and pushes `latest` plus a commit-SHA tag to GHCR.
4. A systemd timer on the LAN server periodically fetches tracked deployment files from `main`, pulls the GHCR image, and recreates the selected Compose services.
5. Secrets remain only in the server-local `.env`, which is ignored by Git.

## Published image

The workflow publishes:

```text
ghcr.io/d0rsha/ha-linux-agent:latest
ghcr.io/d0rsha/ha-linux-agent:sha-<commit>
```

The first GHCR package may be private by default. For this public repository, the simplest deployment is to make the container package public after its first successful publish. Public GHCR container packages can be pulled anonymously.

If the package remains private, log Docker into `ghcr.io` on the LAN server using a GitHub personal access token with package read access before enabling the timer.

## Server installation

Requirements:

- Git
- Docker Engine
- Docker Compose plugin
- systemd

Clone the repository to the path expected by the provided unit:

```bash
sudo git clone https://github.com/d0rsha/Ha-Linux-agent.git /opt/ha-linux-agent
cd /opt/ha-linux-agent
sudo cp .env.example .env
sudo nano .env
```

Keep `.env` local. The deploy script performs `git reset --hard origin/main`, so do not keep local changes in tracked repository files.

Install the deployment configuration and systemd units:

```bash
sudo cp deploy/ha-linux-agent-deploy.example /etc/default/ha-linux-agent-deploy
sudo cp deploy/systemd/ha-linux-agent-deploy.service /etc/systemd/system/
sudo cp deploy/systemd/ha-linux-agent-deploy.timer /etc/systemd/system/
sudo systemctl daemon-reload
```

If the checkout is not `/opt/ha-linux-agent`, update both `DEPLOY_ROOT` in `/etc/default/ha-linux-agent-deploy` and the `ExecStart` path in the service unit.

## Choose services

By default, `DEPLOY_SERVICES` is empty and Compose starts the project's normal unprofiled services plus profiles selected by `COMPOSE_PROFILES` in `.env`.

For an explicit allowlist of long-running services, edit:

```text
/etc/default/ha-linux-agent-deploy
```

For example:

```bash
DEPLOY_SERVICES="ha-agent-telegram openai-mcp-tunnel"
```

Only name services that exist in the merged `main` branch.

## First deployment

Run one deployment manually before enabling the timer:

```bash
sudo systemctl start ha-linux-agent-deploy.service
sudo systemctl status ha-linux-agent-deploy.service
```

Inspect containers and logs:

```bash
cd /opt/ha-linux-agent
docker compose -f compose.yaml -f compose.deploy.yaml ps
docker compose -f compose.yaml -f compose.deploy.yaml logs --tail=100
```

Then enable the five-minute timer:

```bash
sudo systemctl enable --now ha-linux-agent-deploy.timer
systemctl list-timers ha-linux-agent-deploy.timer
```

The timer waits two minutes after boot and then checks every five minutes. The server only makes outbound connections to GitHub/GHCR and any normal application destinations.

## Image selection and rollback

`compose.deploy.yaml` uses this default image:

```text
ghcr.io/d0rsha/ha-linux-agent:latest
```

To pin or roll back, set `HA_AGENT_IMAGE` in the server-local `.env`:

```bash
HA_AGENT_IMAGE=ghcr.io/d0rsha/ha-linux-agent:sha-abc1234
```

Then deploy again:

```bash
sudo systemctl start ha-linux-agent-deploy.service
```

Remove the override to return to `latest`.

## Manual deployment

The same update can be triggered at any time without waiting for the timer:

```bash
sudo systemctl start ha-linux-agent-deploy.service
```

Follow its log with:

```bash
journalctl -u ha-linux-agent-deploy.service -f
```

## Security notes

- No self-hosted GitHub runner is installed on the LAN server.
- No inbound deployment port is required.
- `.env` stays local and is not committed.
- GitHub Actions publishes the image with the repository-scoped `GITHUB_TOKEN`; no long-lived registry write token is stored in the repository.
- The server executes deployment metadata from the trusted `main` branch, so branch protection and review discipline remain part of the security boundary.
