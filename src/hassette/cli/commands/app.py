"""App-related CLI commands: app list, health, activity, config, source."""

from typing import Any

from hassette.cli.client import make_client
from hassette.cli.context import DEFAULT_CLI_CONTEXT, CLIContextParam
from hassette.cli.output import Column, fmt_duration_ms, fmt_relative_time, render_detail, render_table
from hassette.cli.types import InstanceArg, LimitArg, SinceArg, SourceTierArg
from hassette.schemas.telemetry_models import ActivityFeedEntry
from hassette.web.models import AppConfigResponse, AppHealthResponse, AppManifestListResponse, AppSourceResponse

APP_LIST_COLUMNS: list[Column] = [
    Column("app_key", "App Key", max_width=20),
    Column("status", "Status", max_width=10),
    Column("display_name", "Display Name", max_width=22),
    Column("instance_count", "Instances", max_width=9),
    Column("recent_invocations_1h", "Invoc/1h", max_width=8),
    Column("enabled", "Enabled", max_width=7),
    Column("autostart", "Autostart", max_width=9),
    Column("filename", "File", max_width=20),
]


def cmd_app(*, ctx: CLIContextParam = DEFAULT_CLI_CONTEXT) -> None:
    """List all apps (GET /api/apps/manifests)."""
    client = make_client(ctx)
    result = client.get("/api/apps/manifests", AppManifestListResponse)
    render_table(result.manifests, APP_LIST_COLUMNS, json_mode=ctx.json_mode)  # pyright: ignore[reportArgumentType]


APP_HEALTH_COLUMNS: list[Column] = [
    Column("health_status", "Health", max_width=10),
    Column("error_rate", "Error Rate", max_width=10),
    Column("error_rate_class", "Rate Class", max_width=10),
    Column("handler_avg_duration", "Handler Avg", max_width=11, formatter=fmt_duration_ms),
    Column("job_avg_duration", "Job Avg", max_width=9, formatter=fmt_duration_ms),
    Column("last_activity_ts", "Last Active", max_width=11, formatter=fmt_relative_time),
]


def cmd_app_health(
    key: str,
    instance: InstanceArg = None,
    since: SinceArg = None,
    source_tier: SourceTierArg = None,
    *,
    ctx: CLIContextParam = DEFAULT_CLI_CONTEXT,
) -> None:
    """Show health metrics for an app instance (GET /api/telemetry/app/{key}/health)."""
    client = make_client(ctx)

    params: dict[str, Any] = {}
    if instance is not None:
        params["instance_index"] = client.resolve_instance(key, instance)
    if since is not None:
        params["since"] = since
    if source_tier is not None:
        params["source_tier"] = source_tier

    result = client.get(f"/api/telemetry/app/{key}/health", AppHealthResponse, params=params)
    render_detail(result, json_mode=ctx.json_mode)


APP_ACTIVITY_COLUMNS: list[Column] = [
    Column("row_id", "ID", max_width=10),
    Column("kind", "Kind", max_width=8),
    Column("status", "Status", max_width=10),
    Column("app_key", "App", max_width=16),
    Column("handler_name", "Handler", max_width=22),
    Column("duration_ms", "Duration", max_width=9, formatter=fmt_duration_ms),
    Column("timestamp", "When", max_width=11, formatter=fmt_relative_time),
    Column("error_type", "Error", max_width=16),
]


def cmd_app_activity(
    key: str,
    instance: InstanceArg = None,
    since: SinceArg = None,
    limit: LimitArg = None,
    *,
    ctx: CLIContextParam = DEFAULT_CLI_CONTEXT,
) -> None:
    """Show recent activity for an app (GET /api/telemetry/app/{key}/activity)."""
    client = make_client(ctx)

    params: dict[str, Any] = {}
    if instance is not None:
        params["instance_index"] = client.resolve_instance(key, instance)
    if since is not None:
        params["since"] = since
    if limit is not None:
        params["limit"] = limit

    raw: list[Any] = client.get(f"/api/telemetry/app/{key}/activity", list, params=params)
    entries = [ActivityFeedEntry.model_validate(e) for e in raw]
    render_table(entries, APP_ACTIVITY_COLUMNS, json_mode=ctx.json_mode)  # pyright: ignore[reportArgumentType]


def cmd_app_config(
    key: str,
    *,
    ctx: CLIContextParam = DEFAULT_CLI_CONTEXT,
) -> None:
    """Show app configuration (GET /api/apps/{key}/config)."""
    client = make_client(ctx)
    result = client.get(f"/api/apps/{key}/config", AppConfigResponse)
    render_detail(result, json_mode=ctx.json_mode)


def cmd_app_source(
    key: str,
    *,
    ctx: CLIContextParam = DEFAULT_CLI_CONTEXT,
) -> None:
    """Show app source code (GET /api/apps/{key}/source)."""
    client = make_client(ctx)
    result = client.get(f"/api/apps/{key}/source", AppSourceResponse)
    render_detail(result, json_mode=ctx.json_mode)
