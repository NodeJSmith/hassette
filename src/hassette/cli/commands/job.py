"""Job-related CLI commands: job list and execution history."""

from typing import Any

from hassette.cli.client import make_client, query_params
from hassette.cli.context import DEFAULT_CLI_CONTEXT, CLIContextParam
from hassette.cli.output import Column, fmt_duration_ms, fmt_relative_time, render_table
from hassette.cli.types import AppKeyArg, InstanceArg, LimitArg, SinceArg, SourceTierArg
from hassette.schemas.execution_models import Execution
from hassette.schemas.job_models import JobSummary

JOB_EXECUTION_COLUMNS: list[Column] = [
    Column("status", "Status", max_width=10),
    Column("duration_ms", "Duration", max_width=9, formatter=fmt_duration_ms),
    Column("error_type", "Error Type", max_width=20),
    Column("error_message", "Error Message", max_width=28),
    Column("execution_start_ts", "When", max_width=11, formatter=fmt_relative_time),
    Column("execution_id", "Execution ID", max_width=14),
]

#: schedule_status -> schedule_status_reason -> display text, for combinations that override
#: the default per-status text below. ``None`` reason keys are handled by the plain
#: _SCHEDULE_STATUS_TEXT fallback in _next_run_display().
_SCHEDULE_STATUS_REASON_TEXT: dict[tuple[str, str], str] = {
    ("scheduled", "legacy_unknown"): "Legacy status unknown.",
    ("completed", "trigger_error"): "Schedule stopped after trigger error.",
}

#: Fallback text for a null next_run, keyed by schedule_status, when no reason override
#: applies. "scheduled" here means live enrichment ran but returned no concrete timing.
_SCHEDULE_STATUS_TEXT: dict[str, str] = {
    "scheduled": "Timing unavailable.",
    "waiting": "Waiting for entity time.",
    "completed": "Schedule completed.",
    "manual": "Manual only.",
}


def _next_run_display(job: JobSummary) -> str:
    """Status-aware display text for the Next Run column.

    A concrete ``next_run`` always wins (relative-time text). Otherwise the text is chosen
    from ``schedule_status``/``schedule_status_reason`` — null timing no longer means "done";
    it means waiting, completed, manual-only, or (for a nominally scheduled job) that live
    timing is temporarily unavailable.
    """
    if job.next_run is not None:
        return fmt_relative_time(job.next_run)
    if job.schedule_status_reason is not None:
        reason_text = _SCHEDULE_STATUS_REASON_TEXT.get((job.schedule_status, job.schedule_status_reason))
        if reason_text is not None:
            return reason_text
    return _SCHEDULE_STATUS_TEXT.get(job.schedule_status, "")


# JOB_LIST_COLUMNS' next_run column wires _next_run_display, defined immediately above, as its row_formatter
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
    Column("avg_duration_ms", "Avg", max_width=7, formatter=fmt_duration_ms),
    Column("next_run", "Next Run", max_width=11, row_formatter=_next_run_display),
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
        raw: list[Any] = client.get(
            f"/api/telemetry/job/{job_id}/executions",
            list,
            params=query_params(since=since, limit=limit),
        )
        executions = [Execution.model_validate(e) for e in raw]
        render_table(executions, JOB_EXECUTION_COLUMNS, json_mode=ctx.json_mode)  # pyright: ignore[reportArgumentType]
        return

    raw = client.get_with_app_routing(
        global_path="/api/scheduler/jobs",
        per_app_path_template="/api/telemetry/app/{app_key}/jobs",
        model=list,
        app_key=app,
        instance=instance,
        extra_params=query_params(since=since, source_tier=source_tier),
    )
    jobs = [JobSummary.model_validate(e) for e in raw]
    render_table(jobs, JOB_LIST_COLUMNS, json_mode=ctx.json_mode)  # pyright: ignore[reportArgumentType]
