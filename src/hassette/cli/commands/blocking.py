"""Blocking-IO findings CLI command."""

from hassette_wire import BlockingFinding, BlockingFindingsResponse, UnattributedBlockingResponse, UnattributedStall

import hassette.cli.output as cli_output
from hassette.cli.client import make_client, query_params
from hassette.cli.context import DEFAULT_CLI_CONTEXT, CLIContextParam
from hassette.cli.output import Column, fmt_duration_ms, fmt_relative_time, render_table
from hassette.cli.types import AppKeyArg, InstanceArg, SinceArg

TRUNCATED_NOTE = "Showing only the most recently seen call sites: older ones are omitted. Narrow --since to see them."


def fmt_call_site(finding: BlockingFinding) -> str:
    """``file.py:98 in func``, or why there is no call site to show."""
    site = finding.call_site
    if site is None:
        handlers = ", ".join(h.name for h in finding.handlers) or "unknown handler"
        return f"call site not captured ({handlers})"
    location = f"{site.display_path}:{site.lineno} in {site.function}"
    if not finding.call_site_is_user_code:
        return f"detected inside {finding.detected_in_package} ({location})"
    return location


def fmt_calls_into(finding: BlockingFinding) -> str:
    """What the call site called into: the Tier 1 callee frame, or the Tier 2 primitive."""
    if finding.primitive is not None:
        return finding.primitive
    if finding.callee is not None:
        return f"{finding.callee.display_path} {finding.callee.function}"
    return ""


def fmt_instances(finding: BlockingFinding) -> str:
    return ", ".join(inst.name or f"instance {inst.index}" for inst in finding.instances)


def fmt_app_frame(stall: UnattributedStall) -> str:
    frame = stall.app_frame
    return f"{frame.display_path}:{frame.lineno} in {frame.function}" if frame is not None else ""


FINDING_COLUMNS: list[Column] = [
    Column("app_key", "App"),
    Column("instances", "Instances", max_width=24, row_formatter=fmt_instances),
    Column("call_site", "Call site", max_width=44, row_formatter=fmt_call_site),
    Column("callee", "Calls into", max_width=36, row_formatter=fmt_calls_into),
    Column("event_count", "Count"),
    Column("max_stall_ms", "Max", formatter=fmt_duration_ms),
    Column("last_seen_ts", "Last seen", formatter=fmt_relative_time),
]

UNATTRIBUTED_COLUMNS: list[Column] = [
    Column("detected_ts", "When", formatter=fmt_relative_time),
    Column("reason", "Reason"),
    Column("stall_duration_ms", "Stall", formatter=fmt_duration_ms),
    Column("app_frame", "App code in stack", row_formatter=fmt_app_frame),
]


def cmd_blocking(
    app: AppKeyArg = None,
    instance: InstanceArg = None,
    since: SinceArg = None,
    *,
    ctx: CLIContextParam = DEFAULT_CLI_CONTEXT,
) -> None:
    """Show blocking-IO findings: calls that stalled the event loop, grouped by app call site.

    With --app, shows that app's findings (GET /api/telemetry/app/{key}/blocking). Without it,
    shows findings for every app plus loop stalls no app is credited with.
    """
    client = make_client(ctx)

    if app is not None:
        params = query_params(instance_index=client.resolve_instance_or_none(app, instance), since=since)
        findings = client.get(f"/api/telemetry/app/{app}/blocking", BlockingFindingsResponse, params=params)
        if ctx.json_mode:
            cli_output.render_detail(findings, json_mode=True)
            return
        render_table(findings.findings, FINDING_COLUMNS, json_mode=False)
        if findings.truncated:
            cli_output.stderr_console.print(TRUNCATED_NOTE, highlight=False)
        return

    if instance is not None:
        client.error_usage("--instance requires --app")

    params = query_params(since=since)
    findings = client.get("/api/telemetry/blocking/findings", BlockingFindingsResponse, params=params)
    unattributed = client.get("/api/telemetry/blocking/unattributed", UnattributedBlockingResponse, params=params)

    if ctx.json_mode:
        document = {
            "findings": findings.model_dump(mode="json"),
            "unattributed": unattributed.model_dump(mode="json"),
        }
        cli_output.render_detail_dict(document, "Blocking", json_mode=True)
        return

    render_table(findings.findings, FINDING_COLUMNS, json_mode=False)
    if unattributed.total_count:
        cli_output.stdout_console.print(
            f"\nLoop stalls credited to no app: {unattributed.total_count} "
            f"({unattributed.displaced_count} displaced, {unattributed.framework_count} framework)",
            highlight=False,
        )
        render_table(unattributed.recent, UNATTRIBUTED_COLUMNS, json_mode=False)
    if findings.truncated:
        cli_output.stderr_console.print(TRUNCATED_NOTE, highlight=False)
