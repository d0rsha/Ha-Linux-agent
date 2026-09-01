# Container image

HA Linux Agent publishes a container image to GitHub Container Registry after successful tests on `main`.

Published tags:

```text
ghcr.io/d0rsha/ha-linux-agent:latest
ghcr.io/d0rsha/ha-linux-agent:sha-<commit>
```

`latest` follows the most recent successful `main` build. Commit-specific `sha-...` tags are intended for reproducible deployments and rollback.

This repository deliberately does not prescribe a production deployment mechanism. Consumers may use Docker Compose, Kubernetes, a private infrastructure repository, a configuration-management system, or another deployment platform.

The repository-level `compose.yaml` is primarily for local development and manual operation. Production infrastructure should own its own runtime configuration, secret management, service selection, restart policy, networking, and image pinning.

## Example

A production Compose definition can reference the published image directly:

```yaml
services:
  ha-agent:
    image: ghcr.io/d0rsha/ha-linux-agent:latest
    env_file:
      - .env
    restart: unless-stopped
    network_mode: host
    volumes:
      - ha-agent-data:/data

volumes:
  ha-agent-data:
```

For rollback, replace `latest` with a known `sha-...` tag.

## Configuration contract

`.env.example` is the application configuration reference. Deployment repositories should derive their production configuration from it and supply secrets through their own secret-management mechanism.

When a new required application variable is introduced, update `.env.example` in the same application change so downstream deployment repositories can detect and adopt it.
