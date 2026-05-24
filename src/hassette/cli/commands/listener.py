"""Listener-related CLI commands: listener list and invocation history."""

from typing import Any

from hassette.cli.client import HassetteCLIClient
from hassette.cli.output import Column, fmt_duration, fmt_relative_time, render_table
from hassette.cli.types import AppKeyArg, InstanceArg, JsonArg, LimitArg, SinceArg, SourceTierArg
from hassette.config.config import HassetteConfig
from hassette.core.telemetry_models import HandlerInvocation
from hassette.web.models import ListenerWithSummary

# ---------------------------------------------------------------------------
# hassette listener (bare — list all listeners, or filter by app)
# ---------------------------------------------------------------------------

LISTENER_LIST_COLUMNS: list[Column] = [
    Column("listener_id", "ID", max_width=6),
    Column("topic", "Topic", max_width=24),
    Column("handler_method", "Handler", max_width=22),
    Column("listener_kind", "Kind", max_width=12),
    Column("total_invocations", "Total", max_width=7),
    Column("successful", "OK", max_width=6),
    Column("failed", "Fail", max_width=6),
    Column("avg_duration_ms", "Avg", max_width=7, formatter=fmt_duration),
    Column("last_invoked_at", "Last", max_width=9, formatter=fmt_relative_time),
]


def cmd_listener(
    app: AppKeyArg = None,
    instance: InstanceArg = None,
    since: SinceArg = None,
    source_tier: SourceTierArg = None,
    json: JsonArg = False,
) -> None:
    """List listeners (GET /api/bus/listeners or /api/telemetry/app/{key}/listeners)."""
    config = HassetteConfig(token=None)
    client = HassetteCLIClient(config, json_mode=json)

    extra_params: dict[str, Any] = {}
    if since is not None:
        extra_params["since"] = since
    if source_tier is not None:
        extra_params["source_tier"] = source_tier

    raw: list[Any] = client.get_with_app_routing(
        global_path="/api/bus/listeners",
        per_app_path_template="/api/telemetry/app/{app_key}/listeners",
        model=list,
        app_key=app,
        instance=instance,
        extra_params=extra_params or None,
    )
    listeners = [ListenerWithSummary.model_validate(e) for e in raw]
    render_table(listeners, LISTENER_LIST_COLUMNS, json_mode=json)  # pyright: ignore[reportArgumentType]


# ---------------------------------------------------------------------------
# hassette listener <id> — invocation history for a specific listener
# ---------------------------------------------------------------------------

LISTENER_INVOCATION_COLUMNS: list[Column] = [
    Column("status", "Status", max_width=10),
    Column("duration_ms", "Duration", max_width=9, formatter=fmt_duration),
    Column("error_type", "Error Type", max_width=20),
    Column("error_message", "Error Message", max_width=28),
    Column("execution_start_ts", "When", max_width=11, formatter=fmt_relative_time),
    Column("execution_id", "Execution ID", max_width=14),
]


def cmd_listener_detail(
    id: int,
    since: SinceArg = None,
    limit: LimitArg = None,
    json: JsonArg = False,
) -> None:
    """Show invocation history for a listener (GET /api/telemetry/handler/{id}/invocations)."""
    config = HassetteConfig(token=None)
    client = HassetteCLIClient(config, json_mode=json)

    params: dict[str, Any] = {}
    if since is not None:
        params["since"] = since
    if limit is not None:
        params["limit"] = limit

    raw: list[Any] = client.get(
        f"/api/telemetry/handler/{id}/invocations",
        list,
        params=params or None,
    )
    invocations = [HandlerInvocation.model_validate(e) for e in raw]
    render_table(invocations, LISTENER_INVOCATION_COLUMNS, json_mode=json)  # pyright: ignore[reportArgumentType]
