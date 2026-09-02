"""App-related CLI commands: app list, health, activity, config, source, start/stop/reload."""

import sys
from typing import Annotated, Any

from cyclopts import Parameter

from hassette.cli.client import HassetteCLIClient, make_client, query_params
from hassette.cli.context import DEFAULT_CLI_CONTEXT, CLIContextParam
from hassette.cli.output import (
    Column,
    fmt_duration_ms,
    fmt_relative_time,
    render_detail,
    render_detail_dict,
    render_table,
    stderr_console,
)
from hassette.cli.types import InstanceArg, LimitArg, SinceArg, SourceTierArg
from hassette.schemas.execution_models import ActivityFeedEntry
from hassette.web.models import AppConfigResponse, AppHealthResponse, AppManifestListResponse, AppSourceResponse

#: Past-tense verb used in success messages, keyed by action name. Mirrors
#: ``_ACTION_PAST_TENSE`` in ``hassette.web.routes.apps`` (same three actions, same shape), but
#: intentionally lowercase here for CLI message construction vs. capitalized there for log lines.
#: Not shared/imported: the web module lives in the route layer (pulls in FastAPI machinery), so
#: importing its ``AppAction`` type here would be an awkward cross-layer dependency for a
#: three-entry dict that changes in lockstep with the action set defined in this same file.
_ACTION_PAST_TENSE: dict[str, str] = {"start": "started", "stop": "stopped", "reload": "reloaded"}

#: Actions that require interactive confirmation before executing.
_ACTIONS_REQUIRING_CONFIRMATION = {"stop", "reload"}

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


APP_HEALTH_COLUMNS: list[Column] = [
    Column("health_status", "Health", max_width=10),
    Column("error_rate", "Error Rate", max_width=10),
    Column("error_rate_class", "Rate Class", max_width=10),
    Column("handler_avg_duration", "Handler Avg", max_width=11, formatter=fmt_duration_ms),
    Column("job_avg_duration", "Job Avg", max_width=9, formatter=fmt_duration_ms),
    Column("last_activity_ts", "Last Active", max_width=11, formatter=fmt_relative_time),
]
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


def cmd_app(*, ctx: CLIContextParam = DEFAULT_CLI_CONTEXT) -> None:
    """List all apps (GET /api/apps/manifests)."""
    client = make_client(ctx)
    result = client.get("/api/apps/manifests", AppManifestListResponse)
    render_table(result.manifests, APP_LIST_COLUMNS, json_mode=ctx.json_mode)  # pyright: ignore[reportArgumentType]


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
    params = query_params(
        instance_index=client.resolve_instance_or_none(key, instance),
        since=since,
        source_tier=source_tier,
    )
    result = client.get(f"/api/telemetry/app/{key}/health", AppHealthResponse, params=params)
    render_detail(result, json_mode=ctx.json_mode)


# dup-ignore-start: cyclopts derives each command's flags from its signature, so a shared
# filter set has to be restated per command — declaration, not copy-pasted logic.
def cmd_app_activity(
    key: str,
    instance: InstanceArg = None,
    since: SinceArg = None,
    limit: LimitArg = None,
    *,
    ctx: CLIContextParam = DEFAULT_CLI_CONTEXT,
) -> None:
    # dup-ignore-end
    """Show recent activity for an app (GET /api/telemetry/app/{key}/activity)."""
    client = make_client(ctx)
    params = query_params(
        instance_index=client.resolve_instance_or_none(key, instance),
        since=since,
        limit=limit,
    )
    raw: list[Any] = client.get(f"/api/telemetry/app/{key}/activity", list, params=params)
    entries = [ActivityFeedEntry.model_validate(e) for e in raw]
    render_table(entries, APP_ACTIVITY_COLUMNS, json_mode=ctx.json_mode)  # pyright: ignore[reportArgumentType]


def cmd_app_config(
    key: str,
    *,
    ctx: CLIContextParam = DEFAULT_CLI_CONTEXT,
) -> None:
    """Show app configuration (GET /api/apps/{key}/config).

    Renders the app's metadata and masked config values. The fully-inlined
    ``config_schema`` is part of the response but is intentionally not shown — it is a
    large machine-oriented blob, not something a CLI reader needs.
    """
    client = make_client(ctx)
    result = client.get(f"/api/apps/{key}/config", AppConfigResponse)
    # Render every field except config_schema, the large machine-oriented blob. Dumping the
    # model (rather than naming fields) keeps new AppConfigResponse fields visible automatically.
    detail = {field: value for field, value in result.model_dump(mode="json").items() if field != "config_schema"}
    render_detail_dict(detail, "App Config", json_mode=ctx.json_mode)


def cmd_app_source(
    key: str,
    *,
    ctx: CLIContextParam = DEFAULT_CLI_CONTEXT,
) -> None:
    """Show app source code (GET /api/apps/{key}/source)."""
    client = make_client(ctx)
    result = client.get(f"/api/apps/{key}/source", AppSourceResponse)
    render_detail(result, json_mode=ctx.json_mode)


def _action_route(client: HassetteCLIClient, key: str, action: str, instance: str | None) -> str:
    """Build the POST path for an app action, resolving ``--instance`` to an index if given."""
    if instance is None:
        return f"/api/apps/{key}/{action}"
    index = client.resolve_instance(key, instance)
    return f"/api/apps/{key}/instances/{index}/{action}"


def _confirm_action(prompt: str, yes: bool) -> bool:
    """Prompt for confirmation unless ``yes`` bypasses it. Returns ``True`` to proceed."""
    if yes:
        return True
    try:
        response = input(f"{prompt} [y/N] ")
    except EOFError:
        return False
    return response.strip().lower() == "y"


def _action_prompt(key: str, action: str, instance: str | None) -> str:
    """Build the human-readable confirmation prompt for a stop/reload action."""
    if instance is not None:
        return f"{action.capitalize()} instance {instance!r} of {key!r}?"
    return f"{action.capitalize()} app {key!r}?"


def _action_success_message(key: str, action: str, instance: str | None) -> str:
    """Build the past-tense success message for a completed app action."""
    verb = _ACTION_PAST_TENSE[action]
    if instance is not None:
        return f"Instance {instance!r} of {key!r} {verb}"
    return f"App {key!r} {verb}"


def _run_app_action(key: str, action: str, instance: str | None, yes: bool, ctx: CLIContextParam) -> None:
    """Shared implementation for ``start``/``stop``/``reload``: confirm, POST, render result."""
    if action in _ACTIONS_REQUIRING_CONFIRMATION:
        prompt = _action_prompt(key, action, instance)
        if not _confirm_action(prompt, yes):
            stderr_console.print("Aborted.")
            sys.exit(0)

    client = make_client(ctx)
    path = _action_route(client, key, action, instance)
    result = client.post(path)
    message = _action_success_message(key, action, instance)
    detail = {"status": result.status, "app_key": result.app_key, "action": result.action, "message": message}
    render_detail_dict(detail, "App Action", json_mode=ctx.json_mode)


def cmd_app_start(
    key: str,
    instance: InstanceArg = None,
    *,
    ctx: CLIContextParam = DEFAULT_CLI_CONTEXT,
) -> None:
    """Start an app or app instance (POST /api/apps/{key}/start)."""
    _run_app_action(key, "start", instance, yes=True, ctx=ctx)


def cmd_app_stop(
    key: str,
    instance: InstanceArg = None,
    yes: Annotated[bool, Parameter(name=["--yes"], help="Skip the confirmation prompt.", negative=[])] = False,
    *,
    ctx: CLIContextParam = DEFAULT_CLI_CONTEXT,
) -> None:
    """Stop an app or app instance (POST /api/apps/{key}/stop)."""
    _run_app_action(key, "stop", instance, yes=yes, ctx=ctx)


def cmd_app_reload(
    key: str,
    instance: InstanceArg = None,
    yes: Annotated[bool, Parameter(name=["--yes"], help="Skip the confirmation prompt.", negative=[])] = False,
    *,
    ctx: CLIContextParam = DEFAULT_CLI_CONTEXT,
) -> None:
    """Reload an app or app instance (POST /api/apps/{key}/reload)."""
    _run_app_action(key, "reload", instance, yes=yes, ctx=ctx)
