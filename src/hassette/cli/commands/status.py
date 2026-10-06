"""System-level CLI commands: status, telemetry, dashboard."""

from hassette_wire import DashboardAppGridResponse, SystemStatusResponse, TelemetryStatusResponse

from hassette.cli.client import make_client
from hassette.cli.context import DEFAULT_CLI_CONTEXT, CLIContextParam
from hassette.cli.output import Column, fmt_duration_ms, fmt_relative_time, render_detail, render_table

DASHBOARD_COLUMNS: list[Column] = [
    Column("app_key", "App", max_width=20),
    Column("status", "Status", max_width=10),
    Column("total_invocations", "Invocations", max_width=11),
    Column("total_errors", "Errors", max_width=6),
    Column("health.handler_avg_duration_ms", "Handler Avg", max_width=11, formatter=fmt_duration_ms),
    Column("health.job_avg_duration_ms", "Job Avg", max_width=9, formatter=fmt_duration_ms),
    Column("health.last_activity_ts", "Last Active", max_width=11, formatter=fmt_relative_time),
    Column("health.health_status", "Health", max_width=10),
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
    """Show app dashboard grid (GET /api/telemetry/dashboard/app-grid)."""
    client = make_client(ctx)
    result = client.get("/api/telemetry/dashboard/app-grid", DashboardAppGridResponse)
    render_table(result.apps, DASHBOARD_COLUMNS, json_mode=ctx.json_mode)
