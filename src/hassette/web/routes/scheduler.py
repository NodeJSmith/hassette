"""Scheduler jobs and execution history endpoints."""

from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Query

from hassette.web.dependencies import SchedulerDep
from hassette.web.models import ScheduledJobResponse
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
        "owner_id": job.owner_id,
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
    instance_index: Annotated[
        int | None, Query()
    ] = None,  # None = all instances (unlike UI partials which default to 0)
) -> list[dict]:
    jobs = await scheduler.get_all_jobs()
    if app_key:
        jobs = [j for j in jobs if j.app_key == app_key]
    if instance_index is not None:
        jobs = [j for j in jobs if j.instance_index == instance_index]
    return [_job_to_dict(j) for j in jobs]
