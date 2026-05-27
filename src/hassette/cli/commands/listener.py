"""Listener-related CLI commands: listener list and invocation history."""

from typing import Annotated, Any

from cyclopts import Parameter

from hassette.cli.client import make_client
from hassette.cli.context import CLIContext
from hassette.cli.output import Column, fmt_duration_ms, fmt_handler_short, fmt_relative_time, render_table
from hassette.cli.types import AppKeyArg, InstanceArg, LimitArg, SinceArg, SourceTierArg
from hassette.core.telemetry_models import HandlerInvocation
from hassette.web.models import ListenerWithSummary

LISTENER_LIST_COLUMNS: list[Column] = [
    Column("listener_id", "ID", max_width=6),
    Column("app_key", "App", max_width=18),
    Column("entity_id", "Target", max_width=26),
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


def cmd_listener(
    listener_id: int | None = None,
    app: AppKeyArg = None,
    instance: InstanceArg = None,
    since: SinceArg = None,
    source_tier: SourceTierArg = None,
    limit: LimitArg = None,
    *,
    ctx: Annotated[CLIContext, Parameter(parse=False)] = CLIContext(),  # noqa: B008  # pyright: ignore[reportCallInDefaultInitializer]
) -> None:
    """List listeners, or show invocation history for a specific listener."""
    client = make_client(ctx)

    if listener_id is not None:
        params: dict[str, Any] = {}
        if since is not None:
            params["since"] = since
        if limit is not None:
            params["limit"] = limit

        raw: list[Any] = client.get(
            f"/api/telemetry/handler/{listener_id}/invocations",
            list,
            params=params,
        )
        invocations = [HandlerInvocation.model_validate(e) for e in raw]
        render_table(invocations, LISTENER_INVOCATION_COLUMNS, json_mode=ctx.json_mode)  # pyright: ignore[reportArgumentType]
        return

    extra_params: dict[str, Any] = {}
    if since is not None:
        extra_params["since"] = since
    if source_tier is not None:
        extra_params["source_tier"] = source_tier

    raw = client.get_with_app_routing(
        global_path="/api/bus/listeners",
        per_app_path_template="/api/telemetry/app/{app_key}/listeners",
        model=list,
        app_key=app,
        instance=instance,
        extra_params=extra_params,
    )
    listeners = [ListenerWithSummary.model_validate(e) for e in raw]
    render_table(listeners, LISTENER_LIST_COLUMNS, json_mode=ctx.json_mode)  # pyright: ignore[reportArgumentType]
