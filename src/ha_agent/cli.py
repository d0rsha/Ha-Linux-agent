import asyncio
import json
import logging

import typer

from .agent import ask_home
from .config import Settings
from .ha_mcp import HomeAssistantMCP, mcp_tools_to_definitions
from .history import HomeAssistantHistory
from .models import ToolCall
from .policy import PolicyDecision, ToolPolicy

app = typer.Typer(no_args_is_help=True)


def _configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")


def _history_client(settings: Settings) -> HomeAssistantHistory:
    return HomeAssistantHistory(
        base_url=settings.resolved_ha_base_url,
        token=settings.ha_token,
        max_entities=settings.ha_history_max_entities,
        max_history_days=settings.ha_history_max_days,
        max_statistics_days=settings.ha_statistics_max_days,
        max_points=settings.ha_history_max_points,
    )


@app.command()
def ask(
    question: str,
    yes_sensitive: bool = typer.Option(
        False,
        "--yes-sensitive",
        help="Approve sensitive actions for this one invocation without an interactive prompt.",
    ),
) -> None:
    """Ask a one-shot question about the home."""
    _configure_logging()
    settings = Settings()

    def _confirm(call: ToolCall, decision: PolicyDecision) -> bool:
        if yes_sensitive:
            return True
        return typer.confirm(
            f"Approve {decision.tier.value} tool {call.name} with arguments {call.arguments}?",
            default=False,
        )

    typer.echo(asyncio.run(ask_home(settings, question, confirm_sensitive=_confirm)))


@app.command("tools")
def tools_command() -> None:
    """List Home Assistant MCP and local history tools visible to the agent."""
    settings = Settings()

    async def _run() -> None:
        ha = HomeAssistantMCP(settings.ha_mcp_url, settings.ha_token)
        policy = ToolPolicy(settings)
        async with ha.connect() as mcp:
            result = await mcp.list_tools()
            tools = mcp_tools_to_definitions(result.tools)
            if settings.ha_history_enabled:
                async with _history_client(settings) as history:
                    tools.extend(history.tool_definitions())
            visible_names = {tool.name for tool in policy.visible_tools(tools)}
            for tool in tools:
                status = "visible" if tool.name in visible_names else "blocked"
                typer.echo(f"[{status}] {tool.name}: {tool.description}")

    asyncio.run(_run())


@app.command("history")
def history_command(
    entity_ids: str = typer.Argument(..., help="Comma-separated Home Assistant entity IDs."),
    start_time: str = typer.Option(..., "--start", help="RFC3339 start timestamp."),
    end_time: str | None = typer.Option(None, "--end", help="RFC3339 end timestamp."),
    all_changes: bool = typer.Option(
        False, "--all-changes", help="Include non-significant state changes as well."
    ),
) -> None:
    """Read recent Recorder history directly, without using the LLM."""
    settings = Settings()

    async def _run() -> None:
        async with _history_client(settings) as history:
            result = await history.get_history(
                entity_ids=[item.strip() for item in entity_ids.split(",") if item.strip()],
                start_time=start_time,
                end_time=end_time,
                significant_changes_only=not all_changes,
            )
            typer.echo(json.dumps(result, indent=2, ensure_ascii=False))

    asyncio.run(_run())


@app.command("statistics")
def statistics_command(
    statistic_ids: str = typer.Argument(..., help="Comma-separated Home Assistant statistic IDs."),
    start_time: str = typer.Option(..., "--start", help="RFC3339 start timestamp."),
    period: str = typer.Option("hour", "--period", help="5minute, hour, day, week, month, or year."),
    end_time: str | None = typer.Option(None, "--end", help="RFC3339 end timestamp."),
) -> None:
    """Read long-term Recorder statistics directly, without using the LLM."""
    settings = Settings()

    async def _run() -> None:
        async with _history_client(settings) as history:
            result = await history.get_statistics(
                statistic_ids=[item.strip() for item in statistic_ids.split(",") if item.strip()],
                start_time=start_time,
                end_time=end_time,
                period=period,
            )
            typer.echo(json.dumps(result, indent=2, ensure_ascii=False))

    asyncio.run(_run())


@app.command("statistics-list")
def statistics_list_command(
    query: str | None = typer.Option(None, "--query", help="Filter IDs/names."),
    statistic_type: str | None = typer.Option(None, "--type", help="Filter by mean or sum."),
    limit: int = typer.Option(100, "--limit", min=1, max=200),
) -> None:
    """List long-term statistic IDs available from Home Assistant."""
    settings = Settings()

    async def _run() -> None:
        async with _history_client(settings) as history:
            result = await history.list_statistics(
                query=query, statistic_type=statistic_type, limit=limit
            )
            typer.echo(json.dumps(result, indent=2, ensure_ascii=False))

    asyncio.run(_run())


@app.command("provider")
def provider_command() -> None:
    """Show resolved LLM provider configuration without revealing the API key."""
    settings = Settings()
    typer.echo(f"provider={settings.llm_provider}")
    typer.echo(f"model={settings.provider_model}")
    typer.echo(f"api_style={settings.provider_api_style}")
    typer.echo(f"base_url={settings.provider_base_url or 'OpenAI default'}")
