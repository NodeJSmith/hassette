"""Execution-history rendering shared by ``hassette job <id>`` and ``hassette listener <id>``."""

from hassette_wire import Execution

from hassette.cli.client import HassetteCLIClient, parse_wire_list, query_params
from hassette.cli.formatters import fmt_duration_ms, fmt_relative_time
from hassette.cli.output import Column, render_table

EXECUTION_HISTORY_COLUMNS: list[Column] = [
    Column("status", "Status", max_width=10),
    Column("duration_ms", "Duration", max_width=9, formatter=fmt_duration_ms),
    Column("error_type", "Error Type", max_width=20),
    Column("error_message", "Error Message", max_width=28),
    Column("execution_start_ts", "When", max_width=11, formatter=fmt_relative_time),
    Column("execution_id", "Execution ID", max_width=14),
]


def render_execution_history(
    client: HassetteCLIClient, path: str, *, since: float | None, limit: int | None, json_mode: bool
) -> None:
    """Fetch the ``Execution`` rows at ``path`` and render them as a table (or JSON).

    Args:
        client: The CLI client to fetch with.
        path: The telemetry executions endpoint, e.g. ``/api/telemetry/job/{id}/executions``.
        since: Only include executions after this epoch timestamp; ``None`` uses the server default.
        limit: Maximum rows to return; ``None`` uses the server default.
        json_mode: Emit JSON instead of a table.
    """
    raw = client.get(path, list, params=query_params(since=since, limit=limit))
    executions = parse_wire_list(Execution, raw)
    render_table(executions, EXECUTION_HISTORY_COLUMNS, json_mode=json_mode)
