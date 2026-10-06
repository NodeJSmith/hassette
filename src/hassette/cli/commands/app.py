"""App-related CLI commands: the ``hassette app`` listing, health, activity, config, source, start/stop/reload."""

import sys
from typing import Any

from hassette_wire import (
    ActivityFeedEntry,
    AppAction,
    AppConfigResponse,
    AppGridResponse,
    AppHealth,
    AppSourceResponse,
)

import hassette.cli.output as cli_output
from hassette.cli.client import APP_GRID_PATH, make_client, parse_wire_list, query_params
from hassette.cli.context import DEFAULT_CLI_CONTEXT, CLIContextParam
from hassette.cli.types import InstanceActionArg, InstanceArg, LimitArg, SinceArg, SourceTierArg, YesArg
from hassette.const.misc import SECONDS_PER_HOUR

#: Past-tense verb used in success messages, keyed by action. Lowercase for CLI message
#: construction; ``hassette.web.routes.apps`` keeps a capitalized copy for its log lines.
ACTION_PAST_TENSE: dict[AppAction, str] = {"start": "started", "stop": "stopped", "reload": "reloaded"}

#: Actions that require interactive confirmation before executing. Kept in sync by hand with the
#: frontend's per-action `ACTIONS` map (``frontend/src/components/shared/action-buttons.tsx``,
#: `CAN_START`/`CAN_STOP` in ``frontend/src/utils/status.ts``) — no shared source of truth across
#: the CLI/frontend boundary for "which actions exist and what each one needs."
ACTIONS_REQUIRING_CONFIRMATION: frozenset[AppAction] = frozenset({"stop", "reload"})

#: Window for ``hassette app``'s activity column, which its "Invocations/<hours>h" header names.
APP_LIST_WINDOW_SECONDS = SECONDS_PER_HOUR

APP_LIST_COLUMNS: list[cli_output.Column] = [
    cli_output.Column("app.app_key", "App", max_width=20),
    cli_output.Column("app.status", "Status", max_width=10),
    cli_output.Column("app.display_name", "Display Name", max_width=22),
    cli_output.Column("app.instance_count", "Instances", max_width=9),
    cli_output.Column(
        "activity.stats.total_invocations",
        f"Invocations/{APP_LIST_WINDOW_SECONDS // SECONDS_PER_HOUR}h",
        max_width=14,
    ),
    cli_output.Column("app.enabled", "Enabled", max_width=7),
    cli_output.Column("app.autostart", "Autostart", max_width=9),
    cli_output.Column("app.filename", "File", max_width=20),
]

APP_HEALTH_COLUMNS: list[cli_output.Column] = [
    cli_output.Column("health_status", "Health", max_width=10),
    cli_output.Column("error_rate", "Error Rate", max_width=10),
    cli_output.Column("error_rate_class", "Rate Class", max_width=10),
    cli_output.Column("handler_avg_duration_ms", "Handler Avg", max_width=11, formatter=cli_output.fmt_duration_ms),
    cli_output.Column("job_avg_duration_ms", "Job Avg", max_width=9, formatter=cli_output.fmt_duration_ms),
    cli_output.Column("last_activity_ts", "Last Active", max_width=11, formatter=cli_output.fmt_relative_time),
]

APP_ACTIVITY_COLUMNS: list[cli_output.Column] = [
    cli_output.Column("row_id", "ID", max_width=10),
    cli_output.Column("kind", "Kind", max_width=8),
    cli_output.Column("status", "Status", max_width=10),
    cli_output.Column("app_key", "App", max_width=20),
    cli_output.Column("handler_name", "Handler", max_width=22),
    cli_output.Column("duration_ms", "Duration", max_width=9, formatter=cli_output.fmt_duration_ms),
    cli_output.Column("timestamp", "When", max_width=11, formatter=cli_output.fmt_relative_time),
    cli_output.Column("error_type", "Error", max_width=16),
]


def cmd_app(*, ctx: CLIContextParam = DEFAULT_CLI_CONTEXT) -> None:
    """List all apps with their invocations over the last hour (GET /api/telemetry/app-grid).

    Reads the app grid rather than ``GET /api/apps`` because the app summary carries no activity:
    the grid is the one apps-with-activity view, the same the Apps page shows.
    """
    client = make_client(ctx)
    params = query_params(since=cli_output.now_epoch() - APP_LIST_WINDOW_SECONDS)
    result = client.get(APP_GRID_PATH, AppGridResponse, params=params)
    cli_output.warn_missing_activity(result)
    cli_output.render_table(result.apps, APP_LIST_COLUMNS, json_mode=ctx.json_mode)


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
    result = client.get(f"/api/telemetry/app/{key}/health", AppHealth, params=params)
    cli_output.render_detail(result, json_mode=ctx.json_mode)


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
    """Show recent activity for an app (GET /api/telemetry/app/{key}/activity)."""
    # dup-ignore-end
    client = make_client(ctx)
    params = query_params(
        instance_index=client.resolve_instance_or_none(key, instance),
        since=since,
        limit=limit,
    )
    raw: list[Any] = client.get(f"/api/telemetry/app/{key}/activity", list, params=params)
    entries = parse_wire_list(ActivityFeedEntry, raw)
    cli_output.render_table(entries, APP_ACTIVITY_COLUMNS, json_mode=ctx.json_mode)


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
    cli_output.render_detail_dict(detail, "App Config", json_mode=ctx.json_mode)


def cmd_app_source(
    key: str,
    *,
    ctx: CLIContextParam = DEFAULT_CLI_CONTEXT,
) -> None:
    """Show app source code (GET /api/apps/{key}/source)."""
    client = make_client(ctx)
    result = client.get(f"/api/apps/{key}/source", AppSourceResponse)
    cli_output.render_detail(result, json_mode=ctx.json_mode)


def run_app_action(key: str, action: AppAction, instance: str | None, yes: bool, ctx: CLIContextParam) -> None:
    """Shared implementation for ``start``/``stop``/``reload``: confirm, POST, render result."""
    client = make_client(ctx)
    index: int | None = None
    # Text for the prompt/message — the resolved instance_name when known, otherwise the
    # raw --instance selector the operator typed. NOT guaranteed to be the actual
    # instance_name: see resolve_instance_with_name's docstring for when it falls back.
    instance_label: str | None = None
    if instance is not None:
        index, instance_name = client.resolve_instance_with_name(key, instance)
        instance_label = instance_name if instance_name is not None else instance

    if action in ACTIONS_REQUIRING_CONFIRMATION and not yes:
        if ctx.json_mode:
            # input() always writes its prompt to stdout, which would corrupt the
            # single-JSON-document stdout contract in --json mode. Require --yes instead of
            # ever prompting when JSON output is requested.
            client.error_usage(f"--yes is required to {action} in --json mode")
        prompt = (
            f"{action.capitalize()} instance {instance_label!r} of {key!r}?"
            if instance_label is not None
            else f"{action.capitalize()} app {key!r}?"
        )
        try:
            response = input(f"{prompt} [y/N] ")
        except EOFError:
            response = ""
        if response.strip().lower() != "y":
            cli_output.stderr_console.print("Aborted.")
            sys.exit(0)

    result = client.post_with_instance_routing(key, action, index)
    if index is not None and result.instance_index != index:
        cli_output.stderr_console.print(
            f"[bold yellow]Warning:[/bold yellow] requested instance {index} of {key!r} "
            f"but server confirmed instance {result.instance_index!r}",
            highlight=False,
        )

    verb = ACTION_PAST_TENSE[action]
    message = f"Instance {instance_label!r} of {key!r} {verb}" if instance_label is not None else f"App {key!r} {verb}"
    detail = {
        "status": result.status,
        "app_key": result.app_key,
        "action": result.action,
        "instance_index": result.instance_index,
        "message": message,
    }
    cli_output.render_detail_dict(detail, "App Action", json_mode=ctx.json_mode)


def cmd_app_start(
    key: str,
    instance: InstanceActionArg = None,
    *,
    ctx: CLIContextParam = DEFAULT_CLI_CONTEXT,
) -> None:
    """Start an app or app instance (POST /api/apps/{key}/start)."""
    run_app_action(key, "start", instance, yes=True, ctx=ctx)


def cmd_app_stop(
    key: str,
    instance: InstanceActionArg = None,
    yes: YesArg = False,
    *,
    ctx: CLIContextParam = DEFAULT_CLI_CONTEXT,
) -> None:
    """Stop an app or app instance (POST /api/apps/{key}/stop)."""
    run_app_action(key, "stop", instance, yes=yes, ctx=ctx)


def cmd_app_reload(
    key: str,
    instance: InstanceActionArg = None,
    yes: YesArg = False,
    *,
    ctx: CLIContextParam = DEFAULT_CLI_CONTEXT,
) -> None:
    """Reload an app or app instance (POST /api/apps/{key}/reload)."""
    run_app_action(key, "reload", instance, yes=yes, ctx=ctx)
