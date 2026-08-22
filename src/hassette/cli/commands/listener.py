"""Listener-related CLI commands: listener list and invocation history."""

from typing import Any

from hassette.cli.client import make_client, query_params
from hassette.cli.context import DEFAULT_CLI_CONTEXT, CLIContextParam
from hassette.cli.output import Column, fmt_duration_ms, fmt_handler_short, fmt_relative_time, render_table
from hassette.cli.types import AppKeyArg, InstanceArg, LimitArg, SinceArg, SourceTierArg
from hassette.schemas.execution_models import Execution
from hassette.web.models import ListenerWithSummary

LISTENER_LIST_COLUMNS: list[Column] = [
    Column("listener_id", "ID", max_width=6),
    Column("app_key", "App", max_width=18),
    Column("target", "Target", max_width=26),
    Column("listener_kind", "Kind", max_width=12),
    Column("handler_method", "Handler", max_width=22, formatter=fmt_handler_short),
    Column("total_invocations", "Total", max_width=7),
    Column("successful", "OK", max_width=6),
    Column("failed", "Fail", max_width=6),
    Column("avg_duration_ms", "Avg", max_width=7, formatter=fmt_duration_ms),
    Column("last_invoked_at", "Last", max_width=9, formatter=fmt_relative_time),
]

LISTENER_INVOCATION_COLUMNS: list[Column] = [
    Column("status", "Status", max_width=10),
    Column("duration_ms", "Duration", max_width=9, formatter=fmt_duration_ms),
    Column("error_type", "Error Type", max_width=20),
    Column("error_message", "Error Message", max_width=28),
    Column("execution_start_ts", "When", max_width=11, formatter=fmt_relative_time),
    Column("execution_id", "Execution ID", max_width=14),
]


# dup-ignore-start: cyclopts derives each command's flags from its signature, so a shared
# filter set has to be restated per command — declaration, not copy-pasted logic.
def cmd_listener(
    listener_id: int | None = None,
    app: AppKeyArg = None,
    instance: InstanceArg = None,
    since: SinceArg = None,
    source_tier: SourceTierArg = None,
    limit: LimitArg = None,
    *,
    ctx: CLIContextParam = DEFAULT_CLI_CONTEXT,
) -> None:
    # dup-ignore-end
    """List listeners, or show invocation history for a specific listener."""
    client = make_client(ctx)

    if listener_id is not None:
        raw: list[Any] = client.get(
            f"/api/telemetry/listener/{listener_id}/executions",
            list,
            params=query_params(since=since, limit=limit),
        )
        invocations = [Execution.model_validate(e) for e in raw]
        render_table(invocations, LISTENER_INVOCATION_COLUMNS, json_mode=ctx.json_mode)  # pyright: ignore[reportArgumentType]
        return

    raw = client.get_with_app_routing(
        global_path="/api/bus/listeners",
        per_app_path_template="/api/telemetry/app/{app_key}/listeners",
        model=list,
        app_key=app,
        instance=instance,
        extra_params=query_params(since=since, source_tier=source_tier),
    )
    listeners = [ListenerWithSummary.model_validate(e) for e in raw]
    render_table(listeners, LISTENER_LIST_COLUMNS, json_mode=ctx.json_mode)  # pyright: ignore[reportArgumentType]
