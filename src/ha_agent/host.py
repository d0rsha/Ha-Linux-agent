from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .models import ToolDefinition


HOST_TOOL_NAMES = frozenset(
    {
        "GetCpu",
        "GetMemory",
        "GetDiskUsage",
        "GetHostUptime",
        "CheckHostReachability",
        "GetServiceStatus",
        "GetDockerContainers",
        "ReadSelectedLogs",
    }
)

CommandRunner = Callable[[list[str], float], subprocess.CompletedProcess[str]]


def _default_runner(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout,
    )


@dataclass(frozen=True)
class HostConfig:
    hostname: str = "local"
    proc_root: str = "/proc"
    disk_paths: frozenset[str] = frozenset({"/"})
    service_allowlist: frozenset[str] = frozenset()
    docker_socket: str = ""
    docker_allowlist: frozenset[str] = frozenset()
    log_paths: frozenset[str] = frozenset()
    journal_units: frozenset[str] = frozenset()
    log_max_bytes: int = 65536
    log_max_age_seconds: int = 3600
    reachability_targets: frozenset[str] = frozenset()
    reachability_timeout_seconds: float = 3.0


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _parse_kv_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in _read_text(path).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


def _validate_name(value: str, allowlist: frozenset[str], field: str) -> str:
    clean = value.strip()
    if not clean:
        raise ValueError(f"{field} is required")
    if clean not in allowlist:
        raise PermissionError(f"{field} is not allow-listed: {clean}")
    return clean


def _validate_host_port(value: str, allowlist: frozenset[str]) -> tuple[str, int]:
    clean = _validate_name(value, allowlist, "target")
    host, sep, port_text = clean.rpartition(":")
    if not sep or not host:
        raise ValueError("target must be host:port")
    port = int(port_text)
    if port < 1 or port > 65535:
        raise ValueError("target port must be between 1 and 65535")
    return host, port


class HostDiagnostics:
    """Narrow read-only Linux diagnostics with explicit allowlists."""

    def __init__(
        self,
        config: HostConfig,
        runner: CommandRunner | None = None,
    ) -> None:
        self.config = config
        self.runner = runner or _default_runner

    def tool_definitions(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="GetCpu",
                description="Get CPU count, load average, and recent aggregate CPU counters. Read-only.",
                parameters={"type": "object", "properties": {}, "additionalProperties": False},
            ),
            ToolDefinition(
                name="GetMemory",
                description="Get Linux memory and swap summary from /proc/meminfo. Read-only.",
                parameters={"type": "object", "properties": {}, "additionalProperties": False},
            ),
            ToolDefinition(
                name="GetDiskUsage",
                description="Get disk usage for an allow-listed path. Read-only.",
                parameters={
                    "type": "object",
                    "properties": {"path": {"type": "string", "default": "/"}},
                    "additionalProperties": False,
                },
            ),
            ToolDefinition(
                name="GetHostUptime",
                description="Get host uptime and load averages. Read-only.",
                parameters={"type": "object", "properties": {}, "additionalProperties": False},
            ),
            ToolDefinition(
                name="CheckHostReachability",
                description="TCP-connect to an allow-listed host:port target. Read-only.",
                parameters={
                    "type": "object",
                    "properties": {"target": {"type": "string"}},
                    "required": ["target"],
                    "additionalProperties": False,
                },
            ),
            ToolDefinition(
                name="GetServiceStatus",
                description="Get status for an allow-listed systemd unit with systemctl show. Read-only.",
                parameters={
                    "type": "object",
                    "properties": {"service": {"type": "string"}},
                    "required": ["service"],
                    "additionalProperties": False,
                },
            ),
            ToolDefinition(
                name="GetDockerContainers",
                description="List allow-listed Docker containers through an opt-in Docker socket. Read-only.",
                parameters={"type": "object", "properties": {}, "additionalProperties": False},
            ),
            ToolDefinition(
                name="ReadSelectedLogs",
                description="Read bounded lines from an allow-listed log path or journal unit. Read-only.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "journal_unit": {"type": "string"},
                        "max_bytes": {"type": "integer", "minimum": 1},
                    },
                    "additionalProperties": False,
                },
            ),
        ]

    def handles(self, tool_name: str) -> bool:
        return tool_name in HOST_TOOL_NAMES

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        if tool_name == "GetCpu":
            result = self.get_cpu()
        elif tool_name == "GetMemory":
            result = self.get_memory()
        elif tool_name == "GetDiskUsage":
            result = self.get_disk_usage(path=arguments.get("path", "/"))
        elif tool_name == "GetHostUptime":
            result = self.get_host_uptime()
        elif tool_name == "CheckHostReachability":
            result = await self.check_host_reachability(target=arguments["target"])
        elif tool_name == "GetServiceStatus":
            result = self.get_service_status(service=arguments["service"])
        elif tool_name == "GetDockerContainers":
            result = await self.get_docker_containers()
        elif tool_name == "ReadSelectedLogs":
            result = self.read_selected_logs(
                path=arguments.get("path"),
                journal_unit=arguments.get("journal_unit"),
                max_bytes=arguments.get("max_bytes"),
            )
        else:
            raise ValueError(f"Unknown host tool: {tool_name}")
        return json.dumps(result, separators=(",", ":"), ensure_ascii=False)

    @property
    def proc_root(self) -> Path:
        return Path(self.config.proc_root)

    def _base(self) -> dict[str, Any]:
        return {"source": "host_diagnostics", "host": self.config.hostname}

    def get_cpu(self) -> dict[str, Any]:
        stat = _read_text(self.proc_root / "stat").splitlines()
        cpu_line = next((line for line in stat if line.startswith("cpu ")), "")
        counters = [int(value) for value in cpu_line.split()[1:]] if cpu_line else []
        load = _read_text(self.proc_root / "loadavg").split()
        return {
            **self._base(),
            "cpu_count": os.cpu_count() or 1,
            "load_average": {
                "1m": float(load[0]),
                "5m": float(load[1]),
                "15m": float(load[2]),
            },
            "cpu_counters": counters,
        }

    def get_memory(self) -> dict[str, Any]:
        raw = _parse_kv_file(self.proc_root / "meminfo")

        def kib(key: str) -> int | None:
            value = raw.get(key)
            if not value:
                return None
            return int(value.split()[0])

        total = kib("MemTotal")
        available = kib("MemAvailable")
        used = total - available if total is not None and available is not None else None
        return {
            **self._base(),
            "mem_total_kib": total,
            "mem_available_kib": available,
            "mem_used_kib": used,
            "swap_total_kib": kib("SwapTotal"),
            "swap_free_kib": kib("SwapFree"),
        }

    def _allowed_path(self, requested: str, allowlist: frozenset[str], field: str) -> Path:
        clean = requested.strip() or "/"
        path = Path(clean).expanduser().resolve()
        allowed = [Path(item).expanduser().resolve() for item in allowlist]
        if not any(path == base or base in path.parents for base in allowed):
            raise PermissionError(f"{field} is outside the allowlist: {path}")
        return path

    def get_disk_usage(self, path: str = "/") -> dict[str, Any]:
        target = self._allowed_path(path, self.config.disk_paths, "path")
        usage = shutil.disk_usage(target)
        return {
            **self._base(),
            "path": str(target),
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "used_percent": round((usage.used / usage.total) * 100, 2) if usage.total else 0,
        }

    def get_host_uptime(self) -> dict[str, Any]:
        uptime_parts = _read_text(self.proc_root / "uptime").split()
        load = _read_text(self.proc_root / "loadavg").split()
        return {
            **self._base(),
            "uptime_seconds": float(uptime_parts[0]),
            "idle_seconds": float(uptime_parts[1]),
            "load_average": {
                "1m": float(load[0]),
                "5m": float(load[1]),
                "15m": float(load[2]),
            },
        }

    async def check_host_reachability(self, target: str) -> dict[str, Any]:
        if not self.config.reachability_targets:
            raise PermissionError("HOST_REACHABILITY_TARGETS is not configured")
        host, port = _validate_host_port(target, self.config.reachability_targets)
        started = time.monotonic()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=self.config.reachability_timeout_seconds,
            )
            writer.close()
            await writer.wait_closed()
            reachable = True
            error = None
        except (OSError, TimeoutError, asyncio.TimeoutError) as exc:
            reachable = False
            error = f"{type(exc).__name__}: {exc}"
        return {
            **self._base(),
            "target": target,
            "reachable": reachable,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
            "error": error,
        }

    def get_service_status(self, service: str) -> dict[str, Any]:
        if not self.config.service_allowlist:
            raise PermissionError("HOST_SERVICE_ALLOWLIST is not configured")
        unit = _validate_name(service, self.config.service_allowlist, "service")
        result = self.runner(
            [
                "systemctl",
                "show",
                unit,
                "--no-pager",
                "--property=Id,LoadState,ActiveState,SubState,ExecMainStatus,FragmentPath",
            ],
            5.0,
        )
        values: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key] = value
        return {
            **self._base(),
            "service": unit,
            "returncode": result.returncode,
            "status": values,
            "stderr": result.stderr.strip()[:1000],
        }

    async def get_docker_containers(self) -> dict[str, Any]:
        if not self.config.docker_socket:
            raise PermissionError("HOST_DOCKER_SOCKET is not configured")
        if not self.config.docker_allowlist:
            raise PermissionError("HOST_DOCKER_ALLOWLIST is not configured")
        transport = httpx.AsyncHTTPTransport(uds=self.config.docker_socket)
        async with httpx.AsyncClient(transport=transport, base_url="http://docker") as client:
            response = await client.get("/containers/json", params={"all": "1"})
            response.raise_for_status()
            rows = response.json()
        containers = []
        for row in rows if isinstance(rows, list) else []:
            names = [name.lstrip("/") for name in row.get("Names", [])]
            if self.config.docker_allowlist.isdisjoint(names):
                continue
            containers.append(
                {
                    "id": str(row.get("Id", ""))[:12],
                    "names": names,
                    "image": row.get("Image"),
                    "state": row.get("State"),
                    "status": row.get("Status"),
                }
            )
        return {**self._base(), "containers": containers, "returned": len(containers)}

    def _tail_file(self, path: Path, limit: int) -> str:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > limit:
                handle.seek(max(0, size - limit))
            data = handle.read(limit)
        return data.decode("utf-8", errors="replace")

    def read_selected_logs(
        self,
        path: str | None = None,
        journal_unit: str | None = None,
        max_bytes: int | None = None,
    ) -> dict[str, Any]:
        if bool(path) == bool(journal_unit):
            raise ValueError("provide exactly one of path or journal_unit")
        limit = max(1, min(int(max_bytes or self.config.log_max_bytes), self.config.log_max_bytes))
        if path:
            if not self.config.log_paths:
                raise PermissionError("HOST_LOG_PATHS is not configured")
            target = self._allowed_path(path, self.config.log_paths, "path")
            age_seconds = time.time() - target.stat().st_mtime
            if age_seconds > self.config.log_max_age_seconds:
                raise ValueError("log file is older than HOST_LOG_MAX_AGE_SECONDS")
            text = self._tail_file(target, limit)
            return {
                **self._base(),
                "path": str(target),
                "max_bytes": limit,
                "truncated": target.stat().st_size > limit,
                "text": text,
            }
        assert journal_unit is not None
        if not self.config.journal_units:
            raise PermissionError("HOST_JOURNAL_UNITS is not configured")
        unit = _validate_name(journal_unit, self.config.journal_units, "journal_unit")
        result = self.runner(
            [
                "journalctl",
                "--unit",
                unit,
                "--since",
                f"{self.config.log_max_age_seconds} seconds ago",
                "--no-pager",
                "--output=short-iso",
            ],
            10.0,
        )
        text = result.stdout[-limit:]
        return {
            **self._base(),
            "journal_unit": unit,
            "returncode": result.returncode,
            "max_bytes": limit,
            "truncated": len(result.stdout) > limit,
            "text": text,
            "stderr": result.stderr.strip()[:1000],
        }


def host_config_from_settings(settings: Any) -> HostConfig:
    return HostConfig(
        hostname=socket.gethostname(),
        proc_root=settings.host_proc_root,
        disk_paths=settings.host_disk_path_set,
        service_allowlist=settings.host_service_allowlist_set,
        docker_socket=settings.host_docker_socket,
        docker_allowlist=settings.host_docker_allowlist_set,
        log_paths=settings.host_log_path_set,
        journal_units=settings.host_journal_unit_set,
        log_max_bytes=settings.host_log_max_bytes,
        log_max_age_seconds=settings.host_log_max_age_seconds,
        reachability_targets=settings.host_reachability_target_set,
        reachability_timeout_seconds=settings.host_reachability_timeout_seconds,
    )
