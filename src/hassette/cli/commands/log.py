"""Log-related CLI commands: recent log entries and logs by execution."""

from typing import Annotated, Any

from cyclopts import Parameter

from hassette.cli.client import make_client
from hassette.cli.context import CLIContext
from hassette.cli.output import Column, fmt_relative_time, render_table
from hassette.cli.types import AppKeyArg, InstanceArg, LimitArg, SinceArg, SourceTierArg
from hassette.web.models import LogEntryResponse, LogsByExecutionResponse

# Shared log entry column definitions (used by both log and execution)

LOG_COLUMNS: list[Column] = [
    Column("timestamp", "When", formatter=fmt_relative_time),
    Column("level", "Level"),
    Column("app_key", "App"),
    Column("instance_name", "Instance"),
    Column("func_name", "Function"),
    Column("message", "Message"),
]

EXECUTION_LOG_COLUMNS: list[Column] = [
    Column("timestamp", "When", formatter=fmt_relative_time),
    Column("level", "Level"),
    Column("func_name", "Function"),
    Column("lineno", "Line"),
    Column("message", "Message"),
]


def cmd_log(
    app: AppKeyArg = None,
    instance: InstanceArg = None,
    since: SinceArg = None,
    limit: LimitArg = None,
    source_tier: SourceTierArg = None,
    *,
    ctx: Annotated[CLIContext, Parameter(parse=False)] = CLIContext(),  # noqa: B008  # pyright: ignore[reportCallInDefaultInitializer]
) -> None:
    """Show recent log entries (GET /api/logs/recent)."""
    client = make_client(ctx)

    if instance is not None:
        client.error_usage("--instance is not supported on the log command")

    params: dict[str, Any] = {}
    if app is not None:
        params["app_key"] = app
    if since is not None:
        params["since"] = since
    if limit is not None:
        params["limit"] = limit
    if source_tier is not None:
        params["source_tier"] = source_tier

    raw: list[Any] = client.get(
        "/api/logs/recent",
        list,
        params=params,
    )
    entries = [LogEntryResponse.model_validate(e) for e in raw]
    render_table(entries, LOG_COLUMNS, json_mode=ctx.json_mode)  # pyright: ignore[reportArgumentType]


def cmd_execution(
    uuid: str,
    limit: LimitArg = None,
    *,
    ctx: Annotated[CLIContext, Parameter(parse=False)] = CLIContext(),  # noqa: B008  # pyright: ignore[reportCallInDefaultInitializer]
) -> None:
    """Show logs for a specific execution (GET /api/executions/{execution_id})."""
    client = make_client(ctx)

    params: dict[str, Any] = {}
    if limit is not None:
        params["limit"] = limit

    response = client.get(
        f"/api/executions/{uuid}",
        LogsByExecutionResponse,
        params=params,
    )
    render_table(response.records, EXECUTION_LOG_COLUMNS, json_mode=ctx.json_mode)  # pyright: ignore[reportArgumentType]
