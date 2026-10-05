"""System-level CLI commands: status, telemetry, dashboard."""

from hassette_wire import AppGridResponse, SystemStatusResponse, TelemetryStatusResponse

from hassette.cli.client import make_client
from hassette.cli.context import DEFAULT_CLI_CONTEXT, CLIContextParam
from hassette.cli.output import (
    Column,
    fmt_duration_ms,
    fmt_relative_time,
    render_detail,
    render_table,
    warn_missing_activity,
)

DASHBOARD_COLUMNS: list[Column] = [
    Column("app.app_key", "App", max_width=20),
    Column("app.status", "Status", max_width=8),
    Column("activity.stats.total_invocations", "Invoc", max_width=6),
    Column("activity.stats.total_errors", "Errs", max_width=5),
    Column("activity.stats.health.handler_avg_duration_ms", "Handler Avg", max_width=11, formatter=fmt_duration_ms),
    Column("activity.stats.health.job_avg_duration_ms", "Job Avg", max_width=9, formatter=fmt_duration_ms),
    Column("activity.stats.health.last_activity_ts", "Last Active", max_width=11, formatter=fmt_relative_time),
    Column("activity.stats.health.health_status", "Health", max_width=9),
]


def cmd_status(*, ctx: CLIContextParam = DEFAULT_CLI_CONTEXT) -> None:
    """Show system status (GET /api/health)."""
    client = make_client(ctx)
    result = client.get("/api/health", SystemStatusResponse)
    render_detail(result, json_mode=ctx.json_mode)


def cmd_telemetry(*, ctx: CLIContextParam = DEFAULT_CLI_CONTEXT) -> None:
    """Show telemetry database status (GET /api/telemetry/status)."""
    client = make_client(ctx)
    result = client.get("/api/telemetry/status", TelemetryStatusResponse, tolerate_503=True)
    render_detail(result, json_mode=ctx.json_mode)


def cmd_dashboard(*, ctx: CLIContextParam = DEFAULT_CLI_CONTEXT) -> None:
    """Show the app grid with health columns and all-time counts (GET /api/telemetry/app-grid).

    ``hassette app`` reads the same grid over the last hour, with config columns instead of health.
    """
    client = make_client(ctx)
    result = client.get("/api/telemetry/app-grid", AppGridResponse)
    warn_missing_activity([row.activity for row in result.apps], windowed=False)
    render_table(result.apps, DASHBOARD_COLUMNS, json_mode=ctx.json_mode)
