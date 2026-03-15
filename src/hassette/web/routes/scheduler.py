"""Scheduler jobs and execution history endpoints."""

from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Query

from hassette.web.dependencies import SchedulerDep
from hassette.web.models import JobExecutionResponse, ScheduledJobResponse
from hassette.web.utils import resolve_trigger

if TYPE_CHECKING:
    from hassette.scheduler.classes import ScheduledJob

router = APIRouter(tags=["scheduler"])


def _job_to_dict(job: "ScheduledJob") -> dict[str, Any]:
    """Serialize a ScheduledJob to a dict matching ScheduledJobResponse fields.

    NOTE: Distinct from web.ui.context.job_to_dict which targets template rendering.
    This variant includes job_id (for ScheduledJobResponse) and omits app_key/instance_index.
    """
    trigger_type, trigger_detail = resolve_trigger(job)
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
    instance_index: Annotated[int, Query()] = 0,  # noqa: ARG001 — stub until scheduler exposes instance-aware job listing
) -> list[dict]:
    jobs = await scheduler.get_all_jobs()
    if app_key is not None:
        jobs = [j for j in jobs if j.owner == app_key]
    return [_job_to_dict(j) for j in jobs]


@router.get("/scheduler/history", response_model=list[JobExecutionResponse])
async def get_job_history(
    limit: Annotated[int, Query(ge=1, le=1000)] = 50,  # noqa: ARG001
    app_key: Annotated[str | None, Query()] = None,  # noqa: ARG001
    instance_index: Annotated[int, Query()] = 0,  # noqa: ARG001
) -> list[dict]:
    # Stub: get_job_summary returns per-job aggregates, not per-execution records;
    # wiring to JobExecutionResponse is deferred to the owner_id cleanup follow-up.
    return []
