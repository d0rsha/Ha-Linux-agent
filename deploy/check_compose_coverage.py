#!/usr/bin/env python3
"""Fail when a locally built Compose service lacks a deploy image override.

This intentionally checks only the small subset of Compose structure used by this
repository: top-level ``services`` with service-level ``build``/``image`` keys.
It has no third-party dependencies, so CI and the deployment host can run it with
plain Python.
"""

from __future__ import annotations

from pathlib import Path
import sys


def service_keys(path: Path) -> dict[str, set[str]]:
    services: dict[str, set[str]] = {}
    in_services = False
    current: str | None = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()

        if indent == 0:
            in_services = stripped == "services:"
            current = None
            continue
        if not in_services:
            continue

        if indent == 2 and stripped.endswith(":"):
            current = stripped[:-1].strip()
            services.setdefault(current, set())
            continue

        if current and indent == 4 and ":" in stripped:
            key = stripped.split(":", 1)[0].strip()
            services[current].add(key)

    return services


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    base = service_keys(root / "compose.yaml")
    deploy = service_keys(root / "compose.deploy.yaml")

    built = {name for name, keys in base.items() if "build" in keys}
    covered = {name for name, keys in deploy.items() if "image" in keys}

    missing = sorted(built - covered)
    stale = sorted(covered - set(base))

    if missing:
        print("compose.deploy.yaml is missing image overrides for locally built services:", file=sys.stderr)
        for name in missing:
            print(f"  - {name}", file=sys.stderr)
        print("Add each service with HA_AGENT_IMAGE and pull_policy: always.", file=sys.stderr)
        return 1

    if stale:
        print("compose.deploy.yaml contains services not present in compose.yaml:", file=sys.stderr)
        for name in stale:
            print(f"  - {name}", file=sys.stderr)
        return 1

    print(f"Deploy coverage OK: {len(built)} locally built service(s) have image overrides.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
