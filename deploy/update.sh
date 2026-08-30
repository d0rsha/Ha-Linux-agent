#!/usr/bin/env bash
set -euo pipefail

DEPLOY_ROOT="${DEPLOY_ROOT:-/opt/ha-linux-agent}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"
DEPLOY_SERVICES="${DEPLOY_SERVICES:-}"

cd "$DEPLOY_ROOT"

git fetch --quiet origin "$DEPLOY_BRANCH"
git reset --hard "origin/$DEPLOY_BRANCH"

compose=(docker compose -f compose.yaml -f compose.deploy.yaml)
services=()
if [[ -n "$DEPLOY_SERVICES" ]]; then
  read -r -a services <<< "$DEPLOY_SERVICES"
fi

if (( ${#services[@]} > 0 )); then
  "${compose[@]}" pull "${services[@]}"
  "${compose[@]}" up -d --no-build "${services[@]}"
else
  "${compose[@]}" pull
  "${compose[@]}" up -d --no-build --remove-orphans
fi
