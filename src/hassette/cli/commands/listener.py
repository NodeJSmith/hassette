"""Listener-related CLI commands: listener list, invocation history and near-misses."""

from typing import Annotated, Any

from cyclopts import Parameter
from hassette_wire import Execution, ListenerMiss, ListenerSummary
from whenever import Instant

from hassette.cli.client import make_client, parse_wire_list, query_params
from hassette.cli.context import DEFAULT_CLI_CONTEXT, CLIContextParam
from hassette.cli.formatters import fmt_duration_ms, fmt_handler_short, fmt_relative_time
from hassette.cli.output import Column, render_table
from hassette.cli.types import AppKeyArg, InstanceArg, LimitArg, SinceArg, SourceTierArg

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


def fmt_hour(hour_ts: float) -> str:
    """The start of a rollup hour in local time, e.g. ``2026-11-12 14:00``."""
    local = Instant.from_timestamp(hour_ts).to_system_tz()
    return f"{local.year:04d}-{local.month:02d}-{local.day:02d} {local.hour:02d}:00"


def fmt_change(miss: ListenerMiss) -> str:
    """The last dropped event's old and new values, e.g. ``on → off``; empty when the event carried neither."""
    old, new = miss.trigger.old_value, miss.trigger.new_value
    if old is None and new is None:
        return ""
    return f"{old if old is not None else '—'} → {new if new is not None else '—'}"


LISTENER_MISS_COLUMNS: list[Column] = [
    Column("hour_ts", "Hour", max_width=16, formatter=fmt_hour),
    Column("reason", "Reason", max_width=19),
    Column("filter", "Filter", max_width=28, formatter=lambda value: value or ""),
    Column("count", "Count", max_width=7),
    Column("last_ts", "Last", max_width=9, formatter=fmt_relative_time),
    Column("trigger.entity_id", "Entity", max_width=24, formatter=lambda value: value or ""),
    Column("trigger", "Old → New", max_width=28, row_formatter=fmt_change),
]

MISSES_HELP = (
    "Show the listener's near-misses instead of its invocations: hourly counts of events that reached it and "
    "didn't run it, by reason and filter, with the last such event. Requires a listener ID."
)


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
    misses: Annotated[bool, Parameter(help=MISSES_HELP, negative=[])] = False,
    ctx: CLIContextParam = DEFAULT_CLI_CONTEXT,
) -> None:
    # dup-ignore-end
    """List listeners, or show invocation history (or near-misses) for a specific listener."""
    client = make_client(ctx)

    if misses:
        if listener_id is None:
            client.error_usage("--misses requires a listener ID")
        raw_misses: list[Any] = client.get(
            f"/api/telemetry/listener/{listener_id}/misses",
            list,
            params=query_params(since=since, limit=limit),
        )
        render_table(parse_wire_list(ListenerMiss, raw_misses), LISTENER_MISS_COLUMNS, json_mode=ctx.json_mode)
        return

    if listener_id is not None:
        raw: list[Any] = client.get(
            f"/api/telemetry/listener/{listener_id}/executions",
            list,
            params=query_params(since=since, limit=limit),
        )
        invocations = parse_wire_list(Execution, raw)
        render_table(invocations, LISTENER_INVOCATION_COLUMNS, json_mode=ctx.json_mode)
        return

    raw = client.get_with_app_routing(
        global_path="/api/bus/listeners",
        per_app_resource="listeners",
        model=list,
        app_key=app,
        instance=instance,
        extra_params=query_params(since=since, source_tier=source_tier),
    )
    listeners = parse_wire_list(ListenerSummary, raw)
    render_table(listeners, LISTENER_LIST_COLUMNS, json_mode=ctx.json_mode)

