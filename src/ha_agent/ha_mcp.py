from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from .models import ToolDefinition


class HomeAssistantMCP:
    def __init__(self, url: str, token: str) -> None:
        self.url = url
        self.token = token

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[Client]:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        async with httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(30.0, read=300.0),
            follow_redirects=True,
        ) as http_client:
            transport = streamable_http_client(self.url, http_client=http_client, terminate_on_close=True)
            async with Client(transport) as client:
                yield client


class HostMCP(HomeAssistantMCP):
    pass


def mcp_tools_to_definitions(tools: list[Any]) -> list[ToolDefinition]:
    converted: list[ToolDefinition] = []
    for tool in tools:
        schema = getattr(tool, "input_schema", None)
        if schema is None:
            schema = getattr(tool, "inputSchema", None)
        converted.append(ToolDefinition(name=tool.name, description=tool.description or getattr(tool, "title", None) or tool.name, parameters=schema or {"type": "object", "properties": {}}))
    return converted


def mcp_result_to_text(result: Any) -> str:
    structured = getattr(result, "structured_content", None)
    if structured is None:
        structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return str(structured)
    parts: list[str] = []
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        parts.append(text if text else str(block))
    return "\n".join(parts) if parts else "(no result)"
