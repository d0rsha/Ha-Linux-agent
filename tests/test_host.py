import asyncio
import subprocess
import time
from pathlib import Path

import pytest

from ha_agent.config import Settings
from ha_agent.host import HOST_TOOL_NAMES, HostConfig, HostDiagnostics, host_config_from_settings


def write_proc(root: Path) -> None:
    root.mkdir()
    (root / "stat").write_text("cpu  1 2 3 4 5 6 7 8 9 10\n", encoding="utf-8")
    (root / "loadavg").write_text("0.01 0.05 0.15 1/100 123\n", encoding="utf-8")
    (root / "uptime").write_text("100.5 900.25\n", encoding="utf-8")
    (root / "meminfo").write_text(
        "MemTotal:       1000 kB\n"
        "MemAvailable:   600 kB\n"
        "SwapTotal:      200 kB\n"
        "SwapFree:       150 kB\n",
        encoding="utf-8",
    )


def test_proc_tools_read_from_configured_proc_root(tmp_path):
    proc = tmp_path / "proc"
    write_proc(proc)
    host = HostDiagnostics(HostConfig(proc_root=str(proc)))
    assert host.get_cpu()["load_average"]["1m"] == 0.01
    assert host.get_memory()["mem_used_kib"] == 400
    assert host.get_host_uptime()["uptime_seconds"] == 100.5


def test_disk_usage_rejects_non_allowlisted_paths(tmp_path):
    allowed = tmp_path / "allowed"
    denied = tmp_path / "denied"
    allowed.mkdir()
    denied.mkdir()
    host = HostDiagnostics(HostConfig(disk_paths=frozenset({str(allowed)})))
    assert host.get_disk_usage(str(allowed))["path"] == str(allowed.resolve())
    with pytest.raises(PermissionError, match="outside the allowlist"):
        host.get_disk_usage(str(denied))


def test_service_status_uses_fixed_systemctl_argv():
    calls = []

    def runner(argv, timeout):
        calls.append((argv, timeout))
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout="Id=ssh.service\nActiveState=active\nSubState=running\n",
            stderr="",
        )

    host = HostDiagnostics(
        HostConfig(service_allowlist=frozenset({"ssh.service"})),
        runner=runner,
    )
    result = host.get_service_status("ssh.service")
    assert result["status"]["ActiveState"] == "active"
    assert calls == [
        (
            [
                "systemctl",
                "show",
                "ssh.service",
                "--no-pager",
                "--property=Id,LoadState,ActiveState,SubState,ExecMainStatus,FragmentPath",
            ],
            5.0,
        )
    ]
    with pytest.raises(PermissionError, match="not allow-listed"):
        host.get_service_status("bad.service; reboot")


def test_log_read_is_allowlisted_recent_and_bounded(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log_file = log_dir / "app.log"
    log_file.write_text("a" * 100, encoding="utf-8")
    host = HostDiagnostics(
        HostConfig(log_paths=frozenset({str(log_dir)}), log_max_bytes=10)
    )
    result = host.read_selected_logs(path=str(log_file), max_bytes=1000)
    assert result["text"] == "a" * 10
    assert result["truncated"] is True


def test_old_logs_are_rejected(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log_file = log_dir / "app.log"
    log_file.write_text("old", encoding="utf-8")
    old = time.time() - 120
    log_file.touch()
    log_file_stat = log_file.stat()
    import os

    os.utime(log_file, (log_file_stat.st_atime, old))
    host = HostDiagnostics(
        HostConfig(log_paths=frozenset({str(log_dir)}), log_max_age_seconds=1)
    )
    with pytest.raises(ValueError, match="older"):
        host.read_selected_logs(path=str(log_file))


def test_reachability_requires_allowlist():
    host = HostDiagnostics(HostConfig())

    async def run():
        with pytest.raises(PermissionError, match="HOST_REACHABILITY_TARGETS"):
            await host.check_host_reachability("127.0.0.1:1")

    asyncio.run(run())


def test_docker_requires_socket_and_allowlist():
    host = HostDiagnostics(HostConfig())

    async def run():
        with pytest.raises(PermissionError, match="HOST_DOCKER_SOCKET"):
            await host.get_docker_containers()

    asyncio.run(run())


def test_settings_build_host_config():
    settings = Settings(
        _env_file=None,
        ha_mcp_url="http://ha/api/mcp/assist",
        ha_token="token",
        openai_api_key="key",
        host_disk_paths="/,/mnt/data",
        host_service_allowlist="ssh.service",
        host_reachability_targets="ha.local:8123",
    )
    config = host_config_from_settings(settings)
    assert "/" in config.disk_paths
    assert "ssh.service" in config.service_allowlist
    assert "ha.local:8123" in config.reachability_targets


def test_host_tool_names_match_definitions():
    host = HostDiagnostics(HostConfig())
    assert {tool.name for tool in host.tool_definitions()} == HOST_TOOL_NAMES
