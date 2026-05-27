"""System-level CLI commands: status, telemetry, dashboard."""

from hassette.cli.client import make_client
from hassette.cli.context import DEFAULT_CLI_CONTEXT, CLIContextParam
from hassette.cli.output import Column, fmt_duration_ms, fmt_relative_time, render_detail, render_table
from hassette.web.models import DashboardAppGridResponse, SystemStatusResponse, TelemetryStatusResponse


def cmd_status(*, ctx: CLIContextParam = DEFAULT_CLI_CONTEXT) -> None:
    """Show system status (GET /api/health)."""
    client = make_client(ctx)
    result = client.get("/api/health", SystemStatusResponse)
    render_detail(result, json_mode=ctx.json_mode)


def cmd_telemetry(*, ctx: CLIContextParam = DEFAULT_CLI_CONTEXT) -> None:
    """Show telemetry database status (GET /api/telemetry/status)."""
    client = make_client(ctx)
    result = client.get("/api/telemetry/status", TelemetryStatusResponse)
    render_detail(result, json_mode=ctx.json_mode)


DASHBOARD_COLUMNS: list[Column] = [
    Column("app_key", "App", max_width=20),
    Column("status", "Status", max_width=8),
    Column("total_invocations", "Invoc", max_width=6),
    Column("total_errors", "Errs", max_width=5),
    Column("avg_duration_ms", "Avg Dur", max_width=8, formatter=fmt_duration_ms),
    Column("last_activity_ts", "Last Active", max_width=11, formatter=fmt_relative_time),
    Column("health_status", "Health", max_width=9),
]


def cmd_dashboard(*, ctx: CLIContextParam = DEFAULT_CLI_CONTEXT) -> None:
    """Show app dashboard grid (GET /api/telemetry/dashboard/app-grid)."""
    client = make_client(ctx)
    result = client.get("/api/telemetry/dashboard/app-grid", DashboardAppGridResponse)
    render_table(result.apps, DASHBOARD_COLUMNS, json_mode=ctx.json_mode)  # pyright: ignore[reportArgumentType]
