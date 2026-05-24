"""Job-related CLI commands: job list and execution history."""

from typing import Any

from hassette.cli.client import HassetteCLIClient
from hassette.cli.output import Column, fmt_duration, fmt_relative_time, render_table
from hassette.cli.types import AppKeyArg, InstanceArg, JsonArg, LimitArg, SinceArg, SourceTierArg
from hassette.config.config import HassetteConfig
from hassette.core.telemetry_models import JobExecution, JobSummary

# ---------------------------------------------------------------------------
# hassette job (bare — list all jobs, or filter by app)
# ---------------------------------------------------------------------------

JOB_LIST_COLUMNS: list[Column] = [
    Column("job_id", "ID", max_width=6),
    Column("handler_method", "Handler", max_width=22),
    Column("trigger_type", "Trigger", max_width=10),
    Column("trigger_label", "Schedule", max_width=14),
    Column("total_executions", "Total", max_width=7),
    Column("successful", "OK", max_width=6),
    Column("failed", "Fail", max_width=6),
    Column("avg_duration_ms", "Avg", max_width=7, formatter=fmt_duration),
    Column("next_run", "Next Run", max_width=11, formatter=fmt_relative_time),
]


def cmd_job(
    app: AppKeyArg = None,
    instance: InstanceArg = None,
    since: SinceArg = None,
    source_tier: SourceTierArg = None,
    json: JsonArg = False,
) -> None:
    """List scheduled jobs (GET /api/scheduler/jobs or /api/telemetry/app/{key}/jobs)."""
    config = HassetteConfig(token=None)
    client = HassetteCLIClient(config, json_mode=json)

    extra_params: dict[str, Any] = {}
    if since is not None:
        extra_params["since"] = since
    if source_tier is not None:
        extra_params["source_tier"] = source_tier

    raw: list[Any] = client.get_with_app_routing(
        global_path="/api/scheduler/jobs",
        per_app_path_template="/api/telemetry/app/{app_key}/jobs",
        model=list,
        app_key=app,
        instance=instance,
        extra_params=extra_params or None,
    )
    jobs = [JobSummary.model_validate(e) for e in raw]
    render_table(jobs, JOB_LIST_COLUMNS, json_mode=json)  # pyright: ignore[reportArgumentType]


# ---------------------------------------------------------------------------
# hassette job <id> — execution history for a specific job
# ---------------------------------------------------------------------------

JOB_EXECUTION_COLUMNS: list[Column] = [
    Column("status", "Status", max_width=10),
    Column("duration_ms", "Duration", max_width=9, formatter=fmt_duration),
    Column("error_type", "Error Type", max_width=20),
    Column("error_message", "Error Message", max_width=28),
    Column("execution_start_ts", "When", max_width=11, formatter=fmt_relative_time),
    Column("execution_id", "Execution ID", max_width=14),
]


def cmd_job_detail(
    id: int,
    since: SinceArg = None,
    limit: LimitArg = None,
    json: JsonArg = False,
) -> None:
    """Show execution history for a job (GET /api/telemetry/job/{id}/executions)."""
    config = HassetteConfig(token=None)
    client = HassetteCLIClient(config, json_mode=json)

    params: dict[str, Any] = {}
    if since is not None:
        params["since"] = since
    if limit is not None:
        params["limit"] = limit

    raw: list[Any] = client.get(
        f"/api/telemetry/job/{id}/executions",
        list,
        params=params or None,
    )
    executions = [JobExecution.model_validate(e) for e in raw]
    render_table(executions, JOB_EXECUTION_COLUMNS, json_mode=json)  # pyright: ignore[reportArgumentType]
