from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx
from mcp import Client
from mcp.client.streamable_http import streamable_http_client


class HomeAssistantMCP:
    def __init__(self, url: str, token: str) -> None:
        self.url = url
        self.token = token

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[Client]:
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=httpx.Timeout(30.0, read=300.0),
            follow_redirects=True,
        ) as http_client:
            transport = streamable_http_client(
                self.url,
                http_client=http_client,
                terminate_on_close=True,
            )
            async with Client(transport) as client:
                yield client


def mcp_tools_to_openai(tools: list[Any]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for tool in tools:
        converted.append(
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description or tool.title or tool.name,
                "parameters": tool.input_schema or {"type": "object", "properties": {}},
                "strict": False,
            }
        )
    return converted


def mcp_result_to_text(result: Any) -> str:
    if getattr(result, "structured_content", None) is not None:
        return str(result.structured_content)

    parts: list[str] = []
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
        else:
            parts.append(str(block))
    return "\n".join(parts) if parts else "(no result)"
