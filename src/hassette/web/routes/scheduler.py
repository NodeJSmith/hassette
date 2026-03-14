"""Scheduler jobs and execution history endpoints."""

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Query

from hassette.scheduler.classes import CronTrigger, IntervalTrigger
from hassette.web.dependencies import SchedulerDep, TelemetryDep
from hassette.web.models import JobExecutionResponse, ScheduledJobResponse

if TYPE_CHECKING:
    from hassette.scheduler.classes import ScheduledJob

router = APIRouter(tags=["scheduler"])


def _job_to_dict(job: "ScheduledJob") -> dict:
    """Serialize a ScheduledJob to a dict matching ScheduledJobResponse fields."""
    trigger = job.trigger
    if isinstance(trigger, IntervalTrigger):
        trigger_type = "interval"
        trigger_detail: str | None = str(trigger.interval)
    elif isinstance(trigger, CronTrigger):
        trigger_type = "cron"
        trigger_detail = str(trigger.cron_expression)
    else:
        trigger_type = "once"
        trigger_detail = None
    return {
        "job_id": job.db_id or 0,
        "name": job.name,
        "owner": job.owner,
        "next_run": str(job.next_run),
        "repeat": job.repeat,
        "cancelled": job.cancelled,
        "trigger_type": trigger_type,
        "trigger_detail": trigger_detail,
    }


@router.get("/scheduler/jobs", response_model=list[ScheduledJobResponse])
async def get_scheduled_jobs(
    scheduler: SchedulerDep,
    app_key: Annotated[str | None, Query()] = None,
    instance_index: Annotated[int, Query()] = 0,  # noqa: ARG001
) -> list[dict]:
    jobs = await scheduler.get_all_jobs()
    if app_key is not None:
        jobs = [j for j in jobs if j.owner == app_key]
    return [_job_to_dict(j) for j in jobs]


@router.get("/scheduler/history", response_model=list[JobExecutionResponse])
async def get_job_history(
    telemetry: TelemetryDep,
    limit: Annotated[int, Query(ge=1, le=1000)] = 50,  # noqa: ARG001
    app_key: Annotated[str | None, Query()] = None,
    instance_index: Annotated[int, Query()] = 0,
) -> list[dict]:
    if app_key is None:
        return []
    return await telemetry.get_job_summary(app_key=app_key, instance_index=instance_index)
