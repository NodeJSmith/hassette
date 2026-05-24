"""Log-related CLI commands: recent log entries and logs by execution."""

from typing import Any

import hassette.cli.globals as cli_globals
from hassette.cli.client import make_client
from hassette.cli.output import Column, fmt_relative_time, fmt_truncate, render_table
from hassette.cli.types import AppKeyArg, InstanceArg, LimitArg, SinceArg, SourceTierArg
from hassette.web.models import LogEntryResponse, LogsByExecutionResponse

# ---------------------------------------------------------------------------
# Shared log entry column definitions (used by both log and execution)
# ---------------------------------------------------------------------------

LOG_COLUMNS: list[Column] = [
    Column("timestamp", "When", max_width=9, formatter=fmt_relative_time),
    Column("level", "Level", max_width=8),
    Column("app_key", "App", max_width=16),
    Column("instance_name", "Instance", max_width=12),
    Column("func_name", "Function", max_width=18),
    Column("message", "Message", max_width=34, formatter=fmt_truncate(60)),
]

EXECUTION_LOG_COLUMNS: list[Column] = [
    Column("timestamp", "When", max_width=9, formatter=fmt_relative_time),
    Column("level", "Level", max_width=8),
    Column("func_name", "Function", max_width=22),
    Column("lineno", "Line", max_width=5),
    Column("message", "Message", max_width=38, formatter=fmt_truncate(60)),
]

# ---------------------------------------------------------------------------
# hassette log — recent log entries
# ---------------------------------------------------------------------------


def cmd_log(
    app: AppKeyArg = None,
    instance: InstanceArg = None,
    since: SinceArg = None,
    limit: LimitArg = None,
    source_tier: SourceTierArg = None,
) -> None:
    """Show recent log entries (GET /api/logs/recent)."""
    client = make_client()

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
    render_table(entries, LOG_COLUMNS, json_mode=cli_globals.json_mode)  # pyright: ignore[reportArgumentType]


# ---------------------------------------------------------------------------
# hassette execution <uuid> — logs for a specific execution context
# ---------------------------------------------------------------------------


def cmd_execution(
    uuid: str,
    limit: LimitArg = None,
) -> None:
    """Show logs for a specific execution (GET /api/executions/{execution_id})."""
    client = make_client()

    params: dict[str, Any] = {}
    if limit is not None:
        params["limit"] = limit

    response = client.get(
        f"/api/executions/{uuid}",
        LogsByExecutionResponse,
        params=params,
    )
    render_table(response.records, EXECUTION_LOG_COLUMNS, json_mode=cli_globals.json_mode)  # pyright: ignore[reportArgumentType]
