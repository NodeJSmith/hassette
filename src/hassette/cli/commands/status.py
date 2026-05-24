"""System-level CLI commands: status, telemetry, dashboard."""

from hassette.cli.client import HassetteCLIClient
from hassette.cli.output import Column, fmt_duration, fmt_relative_time, render_detail, render_table
from hassette.cli.types import JsonArg
from hassette.config.config import HassetteConfig
from hassette.web.models import DashboardAppGridResponse, SystemStatusResponse, TelemetryStatusResponse


def uptime_fmt(value: object) -> str:
    """Format uptime_seconds as a human-readable duration string."""
    if value is None:
        return ""
    try:
        secs = float(value)  # pyright: ignore[reportArgumentType]
    except (TypeError, ValueError):
        return str(value)
    if secs < 60:
        return f"{secs:.0f}s"
    if secs < 3600:
        m, s = divmod(int(secs), 60)
        return f"{m}m {s}s"
    h, remainder = divmod(int(secs), 3600)
    m, s = divmod(remainder, 60)
    return f"{h}h {m}m {s}s"


def boot_issues_fmt(value: object) -> str:
    """Summarise boot_issues as a count or dash."""
    if value is None or value == []:
        return "—"
    if isinstance(value, list):
        return str(len(value))
    return str(value)


# ---------------------------------------------------------------------------
# hassette status
# ---------------------------------------------------------------------------

STATUS_COLUMNS: list[Column] = [
    Column("status", "Status", max_width=12),
    Column("websocket_connected", "WS", max_width=5),
    Column("uptime_seconds", "Uptime", formatter=uptime_fmt),
    Column("entity_count", "Entities", max_width=8),
    Column("app_count", "Apps", max_width=5),
    Column("version", "Version", max_width=12),
    Column("services_running", "Services", max_width=14),
    Column("boot_issues", "Boot Issues", formatter=boot_issues_fmt),
]


def cmd_status(
    json: JsonArg = False,
) -> None:
    """Show system status (GET /api/health)."""
    config = HassetteConfig(token=None)
    client = HassetteCLIClient(config, json_mode=json)
    result = client.get("/api/health", SystemStatusResponse)
    render_detail(result, json_mode=json)


# ---------------------------------------------------------------------------
# hassette telemetry
# ---------------------------------------------------------------------------


def cmd_telemetry(
    json: JsonArg = False,
) -> None:
    """Show telemetry database status (GET /api/telemetry/status)."""
    config = HassetteConfig(token=None)
    client = HassetteCLIClient(config, json_mode=json)
    result = client.get("/api/telemetry/status", TelemetryStatusResponse)
    render_detail(result, json_mode=json)


# ---------------------------------------------------------------------------
# hassette dashboard
# ---------------------------------------------------------------------------

DASHBOARD_COLUMNS: list[Column] = [
    Column("app_key", "App", max_width=20),
    Column("status", "Status", max_width=8),
    Column("total_invocations", "Invoc", max_width=6),
    Column("total_errors", "Errs", max_width=5),
    Column("avg_duration_ms", "Avg Dur", max_width=8, formatter=fmt_duration),
    Column("last_activity_ts", "Last Active", max_width=11, formatter=fmt_relative_time),
    Column("health_status", "Health", max_width=9),
]


def cmd_dashboard(
    json: JsonArg = False,
) -> None:
    """Show app dashboard grid (GET /api/telemetry/dashboard/app-grid)."""
    config = HassetteConfig(token=None)
    client = HassetteCLIClient(config, json_mode=json)
    result = client.get("/api/telemetry/dashboard/app-grid", DashboardAppGridResponse)
    render_table(result.apps, DASHBOARD_COLUMNS, json_mode=json)  # pyright: ignore[reportArgumentType]
