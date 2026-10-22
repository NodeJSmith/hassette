"""Log-related CLI commands: recent log entries and logs by execution."""

from typing import Any

from hassette_wire import LogEntry, LogsByExecutionResponse

from hassette.cli.client import make_client, parse_wire_list, query_params
from hassette.cli.context import DEFAULT_CLI_CONTEXT, CLIContextParam
from hassette.cli.formatters import fmt_log_author, fmt_relative_time
from hassette.cli.output import Column, render_table
from hassette.cli.types import AppKeyArg, AuthorArg, LimitArg, LogInstanceArg, SinceArg

# Shared log entry column definitions (used by both log and execution)

LOG_COLUMNS: list[Column] = [
    Column("timestamp", "When", formatter=fmt_relative_time),
    Column("level", "Level"),
    Column("author", "Author", formatter=fmt_log_author),
    Column("app_key", "App"),
    Column("instance_name", "Instance"),
    Column("func_name", "Function"),
    Column("message", "Message"),
]

EXECUTION_LOG_COLUMNS: list[Column] = [
    Column("timestamp", "When", formatter=fmt_relative_time),
    Column("level", "Level"),
    Column("author", "Author", formatter=fmt_log_author),
    Column("func_name", "Function"),
    Column("lineno", "Line"),
    Column("message", "Message"),
]


def cmd_log(
    app: AppKeyArg = None,
    instance: LogInstanceArg = None,
    since: SinceArg = None,
    limit: LimitArg = None,
    author: AuthorArg = None,
    *,
    ctx: CLIContextParam = DEFAULT_CLI_CONTEXT,
) -> None:
    """Show recent log entries (GET /api/logs/recent)."""
    client = make_client(ctx)

    if instance is not None:
        client.error_usage("--instance is not supported on the log command")

    raw: list[Any] = client.get(
        "/api/logs/recent",
        list,
        params=query_params(app_key=app, since=since, limit=limit, author=author),
    )
    entries = parse_wire_list(LogEntry, raw)
    render_table(entries, LOG_COLUMNS, json_mode=ctx.json_mode)


# dup-ignore-start: cyclopts derives each command's flags from its signature, so a shared
# filter set has to be restated per command — declaration, not copy-pasted logic.
def cmd_execution(
    uuid: str,
    limit: LimitArg = None,
    author: AuthorArg = None,
    *,
    ctx: CLIContextParam = DEFAULT_CLI_CONTEXT,
) -> None:
    # dup-ignore-end
    """Show logs for a specific execution (GET /api/executions/{execution_id})."""
    client = make_client(ctx)

    response = client.get(
        f"/api/executions/{uuid}",
        LogsByExecutionResponse,
        params=query_params(limit=limit, author=author),
    )
    render_table(response.records, EXECUTION_LOG_COLUMNS, json_mode=ctx.json_mode)
