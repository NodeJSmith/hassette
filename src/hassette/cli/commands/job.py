"""Job-related CLI commands: job list, execution history, and manual trigger."""

from hassette_wire import (
    JobSummary,
    JobTriggerResponse,
    ScheduleStatus,
    ScheduleStatusReason,
    UnknownValue,
)

from hassette.cli.client import make_client, parse_wire_list, query_params
from hassette.cli.commands.executions import render_execution_history
from hassette.cli.context import DEFAULT_CLI_CONTEXT, CLIContextParam
from hassette.cli.formatters import fmt_duration_ms, fmt_relative_time
from hassette.cli.output import Column, render_detail, render_table
from hassette.cli.types import AppKeyArg, InstanceArg, LimitArg, SinceArg, SourceTierArg

#: schedule_status -> schedule_status_reason -> display text, for combinations that override
#: the default per-status text below. ``None`` reason keys are handled by the plain
#: SCHEDULE_STATUS_TEXT fallback in next_run_display().
SCHEDULE_STATUS_REASON_TEXT: dict[tuple[ScheduleStatus, ScheduleStatusReason], str] = {
    (ScheduleStatus.SCHEDULED, ScheduleStatusReason.LEGACY_UNKNOWN): "Legacy status unknown.",
    (ScheduleStatus.COMPLETED, ScheduleStatusReason.TRIGGER_ERROR): "Schedule stopped after trigger error.",
}

#: Fallback text for a null next_run, keyed by schedule_status, when no reason override
#: applies. "scheduled" here means live enrichment ran but returned no concrete timing. Covers
#: every ScheduleStatus member (tested).
SCHEDULE_STATUS_TEXT: dict[ScheduleStatus, str] = {
    ScheduleStatus.SCHEDULED: "Timing unavailable.",
    ScheduleStatus.WAITING: "Waiting for entity time.",
    ScheduleStatus.COMPLETED: "Schedule completed.",
    ScheduleStatus.MANUAL: "Manual only.",
}


def next_run_display(job: JobSummary) -> str:
    """Status-aware display text for the Next Run column.

    A concrete ``next_run`` always wins (relative-time text). Otherwise the text is chosen
    from ``schedule_status``/``schedule_status_reason``: waiting, completed, manual-only, or
    (for a nominally scheduled job) live timing temporarily unavailable. Returns ``""`` only
    for a status this CLI doesn't know.
    """
    if job.next_run is not None:
        return fmt_relative_time(job.next_run)
    status, reason = job.schedule_status, job.schedule_status_reason
    # A newer server may send a status this CLI doesn't know; the Status column shows it raw.
    if isinstance(status, UnknownValue):
        return ""
    # An unknown reason falls back to the status's own text, like a known reason with no override.
    if reason is not None and not isinstance(reason, UnknownValue):
        reason_text = SCHEDULE_STATUS_REASON_TEXT.get((status, reason))
        if reason_text is not None:
            return reason_text
    return SCHEDULE_STATUS_TEXT[status]


JOB_LIST_COLUMNS: list[Column] = [
    Column("job_id", "ID", max_width=6),
    Column("app_key", "App", max_width=18),
    Column("job_name", "Handler", max_width=22),
    Column("trigger_type", "Trigger", max_width=10),
    Column("schedule_status", "Status", max_width=10, formatter=lambda v: str(v).capitalize()),
    Column("mode", "Mode", max_width=9),
    Column("total_executions", "Total", max_width=7),
    Column("successful", "OK", max_width=6),
    Column("failed", "Fail", max_width=6),
    Column("skipped", "Skipped", max_width=7),
    Column("avg_duration_ms", "Avg", max_width=7, formatter=fmt_duration_ms),
    Column("next_run", "Next Run", max_width=11, row_formatter=next_run_display),
]


# dup-ignore-start: cyclopts derives each command's flags from its signature, so a shared
# filter set has to be restated per command — declaration, not copy-pasted logic.
def cmd_job(
    job_id: int | None = None,
    app: AppKeyArg = None,
    instance: InstanceArg = None,
    since: SinceArg = None,
    source_tier: SourceTierArg = None,
    limit: LimitArg = None,
    *,
    ctx: CLIContextParam = DEFAULT_CLI_CONTEXT,
) -> None:
    # dup-ignore-end
    """List scheduled jobs, or show execution history for a specific job."""
    client = make_client(ctx)

    if job_id is not None:
        render_execution_history(
            client, f"/api/telemetry/job/{job_id}/executions", since=since, limit=limit, json_mode=ctx.json_mode
        )
        return

    raw = client.get_with_app_routing(
        global_path="/api/scheduler/jobs",
        per_app_resource="jobs",
        model=list,
        app_key=app,
        instance=instance,
        extra_params=query_params(since=since, source_tier=source_tier),
    )
    jobs = parse_wire_list(JobSummary, raw)
    render_table(jobs, JOB_LIST_COLUMNS, json_mode=ctx.json_mode)


def cmd_job_trigger(job_id: int, *, ctx: CLIContextParam = DEFAULT_CLI_CONTEXT) -> None:
    """Manually fire a scheduled job now, outside its normal schedule.

    Args:
        job_id: The job ID, as shown in the ID column of ``hassette job``.
        ctx: The CLI context for this invocation (output mode and server target).
    """
    client = make_client(ctx)
    result = client.post(f"/api/scheduler/jobs/{job_id}/trigger", JobTriggerResponse)
    render_detail(result, json_mode=ctx.json_mode)
