import asyncio
import json
import logging

import typer

from .agent import ask_home
from .config import Settings
from .ha_mcp import HomeAssistantMCP, mcp_tools_to_definitions
from .history import HomeAssistantHistory
from .host import HostDiagnostics, host_config_from_settings
from .host_mcp import run_host_mcp
from .models import ToolCall
from .policy import PolicyDecision, ToolPolicy
from .reporting import ReportAlreadyRunning, run_report
from .security import redact_text
from .storage import SQLiteStore
from .telegram import run_telegram

app = typer.Typer(no_args_is_help=True)
host_app = typer.Typer(no_args_is_help=True)
memory_app = typer.Typer(no_args_is_help=True)
app.add_typer(host_app, name="host")
app.add_typer(memory_app, name="memory")


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


def _host_client(settings: Settings) -> HostDiagnostics:
    return HostDiagnostics(host_config_from_settings(settings))


def _state_store(settings: Settings) -> SQLiteStore:
    return SQLiteStore(
        settings.state_db_path,
        max_messages_per_session=settings.chat_context_messages,
        conversation_retention_days=settings.conversation_retention_days,
        audit_retention_days=settings.audit_retention_days,
    )


def _echo_json(payload: object) -> None:
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))


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
        return typer.confirm(
            f"Approve {decision.tier.value} tool {call.name} with arguments {call.arguments}?",
            default=False,
        )

    typer.echo(asyncio.run(ask_home(settings, question, confirm_sensitive=_confirm)))


@app.command("report")
def report_command(
    anomalies_only: bool = typer.Option(False, "--anomalies-only", help="Suppress delivery when the model reports no meaningful anomaly."),
) -> None:
    """Generate a non-interactive house-health report for cron/systemd."""
    _configure_logging()
    settings = Settings()
    try:
        result = asyncio.run(run_report(settings, anomalies_only=anomalies_only))
    except ReportAlreadyRunning as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=75) from exc
    except Exception as exc:
        logging.getLogger("ha_agent.report").exception("scheduled report failed")
        typer.echo(f"report failed: {type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if result.suppressed:
        typer.echo("NO_ALERT")
        return
    typer.echo(result.text)
    if settings.report_notify_service and not result.delivered:
        raise typer.Exit(code=2)


@app.command("telegram")
def telegram_command() -> None:
    """Run the persistent Telegram chat transport."""
    _configure_logging()
    settings = Settings()
    if not settings.telegram_bot_token:
        typer.echo("TELEGRAM_BOT_TOKEN is required", err=True)
        raise typer.Exit(code=2)
    if not settings.telegram_allowed_user_ids:
        typer.echo("TELEGRAM_ALLOWED_USERS must explicitly allow at least one user ID", err=True)
        raise typer.Exit(code=2)
    asyncio.run(run_telegram(settings))


@app.command("host-mcp")
def host_mcp_command() -> None:
    """Run the restricted host diagnostics MCP server."""
    _configure_logging()
    run_host_mcp(Settings())


@app.command("tools")
def tools_command() -> None:
    """List Home Assistant MCP and local tools visible to the agent."""
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
            if settings.host_diagnostics_enabled:
                tools.extend(_host_client(settings).tool_definitions())
            visible_names = {tool.name for tool in policy.visible_tools(tools)}
            for tool in tools:
                status = "visible" if tool.name in visible_names else "blocked"
                typer.echo(f"[{status}] {tool.name}: {tool.description}")

    asyncio.run(_run())


@memory_app.command("list")
def memory_list_command(
    query: str | None = typer.Option(None, "--query"),
    limit: int = typer.Option(20, "--limit", min=1, max=200),
) -> None:
    """Inspect explicitly selected long-term memory."""
    items = _state_store(Settings()).list_memories(limit=limit, query=query)
    _echo_json([item.__dict__ for item in items])


@memory_app.command("set")
def memory_set_command(key: str, value: str) -> None:
    """Create or replace one explicit long-term memory item."""
    settings = Settings()
    safe_key = redact_text(key, settings.secrets_for_redaction)
    safe_value = redact_text(value, settings.secrets_for_redaction)
    if "[REDACTED]" in safe_key or "[REDACTED]" in safe_value:
        typer.echo("Refusing to store a configured secret in memory.", err=True)
        raise typer.Exit(code=2)
    _state_store(settings).set_memory(safe_key, safe_value)
    typer.echo(f"stored memory: {safe_key}")


@memory_app.command("delete")
def memory_delete_command(key: str) -> None:
    """Delete one long-term memory item without touching audit history."""
    deleted = _state_store(Settings()).delete_memory(key)
    if not deleted:
        typer.echo("memory not found", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"deleted memory: {key}")


@app.command("audit")
def audit_command(limit: int = typer.Option(100, "--limit", min=1, max=500)) -> None:
    """Inspect SQLite tool-call audit metadata."""
    _echo_json(_state_store(Settings()).list_audit(limit=limit))


@host_app.command("cpu")
def host_cpu_command() -> None:
    _echo_json(_host_client(Settings()).get_cpu())


@host_app.command("memory")
def host_memory_command() -> None:
    _echo_json(_host_client(Settings()).get_memory())


@host_app.command("disk")
def host_disk_command(path: str = typer.Option("/", "--path")) -> None:
    _echo_json(_host_client(Settings()).get_disk_usage(path=path))


@host_app.command("uptime")
def host_uptime_command() -> None:
    _echo_json(_host_client(Settings()).get_host_uptime())


@host_app.command("reachability")
def host_reachability_command(target: str = typer.Argument(...)) -> None:
    async def _run() -> None:
        _echo_json(await _host_client(Settings()).check_host_reachability(target=target))
    asyncio.run(_run())


@host_app.command("service")
def host_service_command(service: str = typer.Argument(...)) -> None:
    _echo_json(_host_client(Settings()).get_service_status(service=service))


@host_app.command("docker")
def host_docker_command() -> None:
    async def _run() -> None:
        _echo_json(await _host_client(Settings()).get_docker_containers())
    asyncio.run(_run())


@host_app.command("logs")
def host_logs_command(
    path: str | None = typer.Option(None, "--path"),
    journal_unit: str | None = typer.Option(None, "--journal-unit"),
    max_bytes: int | None = typer.Option(None, "--max-bytes", min=1),
) -> None:
    _echo_json(_host_client(Settings()).read_selected_logs(path=path, journal_unit=journal_unit, max_bytes=max_bytes))


@app.command("history")
def history_command(
    entity_ids: str = typer.Argument(..., help="Comma-separated Home Assistant entity IDs."),
    start_time: str = typer.Option(..., "--start", help="RFC3339 start timestamp."),
    end_time: str | None = typer.Option(None, "--end", help="RFC3339 end timestamp."),
    all_changes: bool = typer.Option(False, "--all-changes", help="Include non-significant state changes as well."),
) -> None:
    settings = Settings()
    async def _run() -> None:
        async with _history_client(settings) as history:
            result = await history.get_history(
                entity_ids=[item.strip() for item in entity_ids.split(",") if item.strip()],
                start_time=start_time,
                end_time=end_time,
                significant_changes_only=not all_changes,
            )
            _echo_json(result)
    asyncio.run(_run())


@app.command("statistics")
def statistics_command(
    statistic_ids: str = typer.Argument(..., help="Comma-separated Home Assistant statistic IDs."),
    start_time: str = typer.Option(..., "--start", help="RFC3339 start timestamp."),
    period: str = typer.Option("hour", "--period", help="5minute, hour, day, week, month, or year."),
    end_time: str | None = typer.Option(None, "--end", help="RFC3339 end timestamp."),
) -> None:
    settings = Settings()
    async def _run() -> None:
        async with _history_client(settings) as history:
            _echo_json(await history.get_statistics(
                statistic_ids=[item.strip() for item in statistic_ids.split(",") if item.strip()],
                start_time=start_time,
                end_time=end_time,
                period=period,
            ))
    asyncio.run(_run())


@app.command("statistics-list")
def statistics_list_command(
    query: str | None = typer.Option(None, "--query", help="Filter IDs/names."),
    statistic_type: str | None = typer.Option(None, "--type", help="Filter by mean or sum."),
    limit: int = typer.Option(100, "--limit", min=1, max=200),
) -> None:
    settings = Settings()
    async def _run() -> None:
        async with _history_client(settings) as history:
            _echo_json(await history.list_statistics(query=query, statistic_type=statistic_type, limit=limit))
    asyncio.run(_run())


@app.command("provider")
def provider_command() -> None:
    settings = Settings()
    typer.echo(f"provider={settings.llm_provider}")
    typer.echo(f"model={settings.provider_model}")
    typer.echo(f"api_style={settings.provider_api_style}")
    typer.echo(f"base_url={settings.provider_base_url or 'OpenAI default'}")
