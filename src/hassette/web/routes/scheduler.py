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
    trigger_label = job.trigger.trigger_label() if job.trigger is not None else ""
    # Serialise fire_at only when jitter is actually configured — matches the documented
    # API contract ("fire_at is present iff jitter was applied"). Using `job.jitter is not
    # None` instead of `job.fire_at != job.next_run` decouples the REST gate from an
    # internal invariant that could change if a future non-jitter reason shifts fire_at.
    fire_at = job.fire_at.format_iso() if job.jitter is not None else None
    return {
        "job_id": job.db_id,
        "name": job.name,
        "owner_id": job.owner_id,
        "next_run": str(job.next_run),
        "repeat": False,  # WP04: repeat field removed from ScheduledJob; triggers handle recurrence
        "cancelled": job.cancelled,
        "trigger_type": trigger_type,
        "trigger_label": trigger_label,
        "trigger_detail": trigger_detail,
        "fire_at": fire_at,
        "jitter": job.jitter,
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
