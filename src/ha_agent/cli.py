import asyncio

import typer

from .agent import ask_home
from .config import Settings
from .ha_mcp import HomeAssistantMCP

app = typer.Typer(no_args_is_help=True)


@app.command()
def ask(question: str) -> None:
    """Ask a one-shot question about the home."""
    settings = Settings()
    typer.echo(asyncio.run(ask_home(settings, question)))


@app.command("tools")
def tools_command() -> None:
    """List the Home Assistant MCP tools visible to the agent."""
    settings = Settings()

    async def _run() -> None:
        ha = HomeAssistantMCP(settings.ha_mcp_url, settings.ha_token)
        async with ha.connect() as mcp:
            result = await mcp.list_tools()
            for tool in result.tools:
                typer.echo(f"{tool.name}: {tool.description or tool.title or ''}")

    asyncio.run(_run())
