import asyncio
import logging

import typer

from .agent import ask_home
from .config import Settings
from .ha_mcp import HomeAssistantMCP, mcp_tools_to_definitions
from .models import ToolCall
from .policy import PolicyDecision, ToolPolicy

app = typer.Typer(no_args_is_help=True)


def _configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")


@app.command()
def ask(
    question: str,
    yes_sensitive: bool = typer.Option(False, "--yes-sensitive", help="Approve sensitive actions for this one invocation without an interactive prompt."),
) -> None:
    """Ask a one-shot question about the home."""
    _configure_logging()
    settings = Settings()

    def _confirm(call: ToolCall, decision: PolicyDecision) -> bool:
        if yes_sensitive:
            return True
        return typer.confirm(f"Approve {decision.tier.value} tool {call.name} with arguments {call.arguments}?", default=False)

    typer.echo(asyncio.run(ask_home(settings, question, confirm_sensitive=_confirm)))


@app.command("tools")
def tools_command() -> None:
    """List Home Assistant MCP tools and whether the local policy exposes them."""
    settings = Settings()

    async def _run() -> None:
        ha = HomeAssistantMCP(settings.ha_mcp_url, settings.ha_token)
        policy = ToolPolicy(settings)
        async with ha.connect() as mcp:
            result = await mcp.list_tools()
            tools = mcp_tools_to_definitions(result.tools)
            visible_names = {tool.name for tool in policy.visible_tools(tools)}
            for tool in tools:
                status = "visible" if tool.name in visible_names else "blocked"
                typer.echo(f"[{status}] {tool.name}: {tool.description}")

    asyncio.run(_run())


@app.command("provider")
def provider_command() -> None:
    """Show resolved LLM provider configuration without revealing the API key."""
    settings = Settings()
    typer.echo(f"provider={settings.llm_provider}")
    typer.echo(f"model={settings.provider_model}")
    typer.echo(f"api_style={settings.provider_api_style}")
    typer.echo(f"base_url={settings.provider_base_url or 'OpenAI default'}")
