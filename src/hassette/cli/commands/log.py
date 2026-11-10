"""Log-related CLI commands: recent log entries and logs by execution."""

from typing import Any

from hassette_wire import Execution, LogEntry, LogsByExecutionResponse
from rich.markup import escape

import hassette.cli.output as cli_output
from hassette.cli.client import make_client, parse_wire_list, query_params
from hassette.cli.context import DEFAULT_CLI_CONTEXT, CLIContextParam
from hassette.cli.formatters import EMPTY_VALUE, fmt_duration_ms, fmt_log_author, fmt_log_message, fmt_relative_time
from hassette.cli.output import Column, render_detail_dict, render_table
from hassette.cli.types import AppKeyArg, AuthorArg, LevelArg, LimitArg, LogInstanceArg, SinceArg

EXECUTION_NOT_FOUND_MESSAGE = (
    "Execution record not found: not recorded yet (rows are written in batches) or removed by "
    "retention; retry in a few seconds."
)

# Shared log entry column definitions (used by both log and execution)

LOG_COLUMNS: list[Column] = [
    Column("timestamp", "When", formatter=fmt_relative_time),
    Column("level", "Level"),
    Column("author", "Author", formatter=fmt_log_author),
    Column("app_key", "App"),
    Column("instance_name", "Instance"),
    Column("func_name", "Function"),
    Column("message", "Message", wrap=True, overflow="fold", row_formatter=fmt_log_message),
]

EXECUTION_LOG_COLUMNS: list[Column] = [
    Column("timestamp", "When", formatter=fmt_relative_time),
    Column("level", "Level"),
    Column("author", "Author", formatter=fmt_log_author),
    Column("func_name", "Function"),
    Column("lineno", "Line"),
    Column("message", "Message", wrap=True, overflow="fold", row_formatter=fmt_log_message),
]


def cmd_log(
    app: AppKeyArg = None,
    instance: LogInstanceArg = None,
    since: SinceArg = None,
    limit: LimitArg = None,
    author: AuthorArg = None,
    level: LevelArg = None,
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
        params=query_params(app_key=app, since=since, limit=limit, author=author, level=level),
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
    """Show an execution's summary, its trigger, and its logs.

    Reads GET /api/telemetry/execution/{execution_id} for the record and GET
    /api/executions/{execution_id} for the logs. A missing or unreadable record doesn't stop the
    logs from showing: ``--json`` holds ``"execution": null`` and the command still exits 0.
    """
    client = make_client(ctx)

    response = client.get(
        f"/api/executions/{uuid}",
        LogsByExecutionResponse,
        params=query_params(limit=limit, author=author),
    )
    execution, failure = client.try_get_nullable(f"/api/telemetry/execution/{uuid}", Execution)
    if failure is not None:
        cli_output.stderr_console.print(
            f"[yellow]Warning:[/yellow] could not read the execution record: {escape(failure)}", highlight=False
        )

    if ctx.json_mode:
        document = {
            "execution": execution.model_dump(mode="json") if execution is not None else None,
            "logs": [entry.model_dump(mode="json") for entry in response.records],
        }
        render_detail_dict(document, "Execution", json_mode=True)
        return

    if execution is not None:
        render_detail_dict(execution_summary(execution), "Execution", json_mode=False)
    elif failure is None:  # a failed lookup already warned above
        cli_output.stderr_console.print(EXECUTION_NOT_FOUND_MESSAGE, highlight=False)
    render_table(response.records, EXECUTION_LOG_COLUMNS, json_mode=False)


def execution_summary(execution: Execution) -> dict[str, Any]:
    """The human-mode summary block: outcome and timing, plus a Trigger section for handler runs."""
    summary: dict[str, Any] = {
        "kind": execution.kind,
        "status": execution.status,
        "started": fmt_relative_time(execution.execution_start_ts),
        "duration": fmt_duration_ms(execution.duration_ms),
    }
    if execution.trigger_mode is not None:
        summary["trigger_mode"] = execution.trigger_mode
    if execution.error_type is not None:
        message = execution.error_message
        summary["error"] = f"{execution.error_type}: {message}" if message else execution.error_type
    trigger = execution.trigger
    if trigger is not None:
        has_change = trigger.old_value is not None or trigger.new_value is not None
        fields = {
            "topic": trigger.topic,
            "entity": trigger.entity_id,
            "change": f"{display_value(trigger.old_value)} → {display_value(trigger.new_value)}"
            if has_change
            else None,
            "context_id": trigger.context_id,
            "parent_id": trigger.parent_id,
            "origin": trigger.origin,
        }
        summary["trigger"] = fields
    return summary


def display_value(value: str | None) -> str:
    """A trigger value for the change line: ``—`` only when there is no value, and ``""`` shown quoted."""
    if value is None:
        return EMPTY_VALUE
    return '""' if value == "" else value
