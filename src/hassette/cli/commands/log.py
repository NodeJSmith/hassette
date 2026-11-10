"""Log-related CLI commands: recent log entries, and one execution's detail (record, API writes, logs)."""

from typing import Any

from hassette_wire import CausingWrite, Execution, ExecutionDetailResponse, LogEntry

import hassette.cli.output as cli_output
from hassette.cli.client import make_client, parse_wire_list, query_params
from hassette.cli.context import DEFAULT_CLI_CONTEXT, CLIContextParam
from hassette.cli.formatters import EMPTY_VALUE, fmt_duration_ms, fmt_log_author, fmt_log_message, fmt_relative_time
from hassette.cli.output import Column, render_detail_dict, render_table
from hassette.cli.types import AppKeyArg, AuthorArg, LevelArg, LimitArg, LogInstanceArg, SinceArg

API_WRITES_TRUNCATED_MESSAGE = "{shown} API writes shown; more were omitted. Raise --limit to see them."

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


def fmt_write_target(target: dict[str, list[str]] | None) -> str:
    """A write's target ids: bare entity ids, other keys prefixed with their name; ``—`` when there is none."""
    if not target:
        return EMPTY_VALUE
    parts: list[str] = []
    for key, ids in target.items():
        joined = ", ".join(ids)
        parts.append(joined if key == "entity_id" else f"{key}: {joined}")
    return "; ".join(parts)


API_WRITE_COLUMNS: list[Column] = [
    Column("sent_ts", "Sent", formatter=fmt_relative_time),
    Column("kind", "Kind"),
    Column("operation", "Operation"),
    Column("target", "Target", wrap=True, overflow="fold", formatter=fmt_write_target),
    Column("outcome", "Outcome"),
    Column("error_code", "Error"),
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
    """Show an execution's summary, its trigger, the API writes it made, and its logs.

    Reads GET /api/executions/{execution_id}. ``--limit`` caps the writes and the logs separately, and
    ``--author`` filters the logs only. ``--json`` prints the response as served; its ``execution`` is null
    while the record isn't written yet.
    """
    client = make_client(ctx)

    detail = client.get(
        f"/api/executions/{uuid}",
        ExecutionDetailResponse,
        params=query_params(limit=limit, author=author),
    )

    if ctx.json_mode:
        render_detail_dict(detail.model_dump(mode="json"), "Execution", json_mode=True)
        return

    if detail.execution is not None:
        render_detail_dict(execution_summary(detail.execution), "Execution", json_mode=False)
    else:
        cli_output.stderr_console.print(EXECUTION_NOT_FOUND_MESSAGE, highlight=False)
    if detail.api_writes:
        render_table(detail.api_writes, API_WRITE_COLUMNS, json_mode=False)
    if detail.api_writes_truncated:
        cli_output.stderr_console.print(
            API_WRITES_TRUNCATED_MESSAGE.format(shown=len(detail.api_writes)), highlight=False
        )
    render_table(detail.logs, EXECUTION_LOG_COLUMNS, json_mode=False)


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
            "caused_by": fmt_caused_by(trigger.caused_by) if trigger.caused_by is not None else None,
        }
        summary["trigger"] = fields
    return summary


def display_value(value: str | None) -> str:
    """A trigger value for the change line: ``—`` only when there is no value, and ``""`` shown quoted."""
    if value is None:
        return EMPTY_VALUE
    return '""' if value == "" else value


def fmt_caused_by(caused_by: CausingWrite) -> str:
    """Which app's write fired the run: ``app/instance kind operation (execution id)``."""
    text = f"{caused_by.app_key}/{caused_by.instance_name} {caused_by.kind}"
    if caused_by.operation is not None:
        text += f" {caused_by.operation}"
    if caused_by.execution_id is not None:
        text += f" (execution {caused_by.execution_id})"
    return text
