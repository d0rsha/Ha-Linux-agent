from __future__ import annotations

import asyncio
from typing import Any

from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer

from .config import Settings
from .host import HostDiagnostics, host_config_from_settings


class StaticTokenVerifier:
    def __init__(self, token: str) -> None:
        self.token = token

    async def verify_token(self, token: str) -> AccessToken | None:
        if not self.token or token != self.token:
            return None
        return AccessToken(
            token=token,
            client_id="ha-linux-agent",
            scopes=["host:read"],
            resource="ha-linux-agent-host-mcp",
        )


def build_host_mcp_server(settings: Settings) -> MCPServer[Any]:
    if not settings.host_mcp_token:
        raise ValueError("HOST_MCP_TOKEN is required to run host-mcp")
    diagnostics = HostDiagnostics(host_config_from_settings(settings))
    resource_url = f"http://{settings.host_mcp_bind}:{settings.host_mcp_port}/mcp"
    auth = AuthSettings(
        issuer_url=resource_url,
        resource_server_url=resource_url,
        required_scopes=["host:read"],
    )
    verifier = StaticTokenVerifier(settings.host_mcp_token)

    server = MCPServer(
        name="ha-linux-agent-host",
        title="HA Linux Agent Host Diagnostics",
        description="Restricted read-only Linux host diagnostics.",
        auth=auth,
        token_verifier=verifier,
    )

    @server.tool(name="GetCpu", description="Get CPU count, load average, and counters. Read-only.")
    def get_cpu() -> dict[str, Any]:
        return diagnostics.get_cpu()

    @server.tool(name="GetMemory", description="Get memory and swap summary. Read-only.")
    def get_memory() -> dict[str, Any]:
        return diagnostics.get_memory()

    @server.tool(name="GetDiskUsage", description="Get allow-listed disk path usage. Read-only.")
    def get_disk_usage(path: str = "/") -> dict[str, Any]:
        return diagnostics.get_disk_usage(path=path)

    @server.tool(name="GetHostUptime", description="Get uptime and load averages. Read-only.")
    def get_host_uptime() -> dict[str, Any]:
        return diagnostics.get_host_uptime()

    @server.tool(name="CheckHostReachability", description="Check allow-listed TCP target. Read-only.")
    async def check_host_reachability(target: str) -> dict[str, Any]:
        return await diagnostics.check_host_reachability(target=target)

    @server.tool(name="GetServiceStatus", description="Get allow-listed systemd unit status. Read-only.")
    def get_service_status(service: str) -> dict[str, Any]:
        return diagnostics.get_service_status(service=service)

    @server.tool(name="GetDockerContainers", description="List allow-listed Docker containers. Read-only.")
    async def get_docker_containers() -> dict[str, Any]:
        return await diagnostics.get_docker_containers()

    @server.tool(name="ReadSelectedLogs", description="Read bounded allow-listed logs. Read-only.")
    def read_selected_logs(
        path: str | None = None,
        journal_unit: str | None = None,
        max_bytes: int | None = None,
    ) -> dict[str, Any]:
        return diagnostics.read_selected_logs(
            path=path,
            journal_unit=journal_unit,
            max_bytes=max_bytes,
        )

    return server


def run_host_mcp(settings: Settings) -> None:
    server = build_host_mcp_server(settings)
    asyncio.run(
        server.run_streamable_http_async(
            host=settings.host_mcp_bind,
            port=settings.host_mcp_port,
            streamable_http_path="/mcp",
        )
    )
