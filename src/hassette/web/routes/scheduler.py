"""Global scheduler jobs endpoint for the Hassette Web API.

Returns all scheduled jobs across all apps, enriched with live heap data.
"""

from fastapi import APIRouter, HTTPException, Query, Response

import hassette.utils.date_utils as date_utils
from hassette.schemas.telemetry_models import JobSummary
from hassette.types.enums import ExecutionMode
from hassette.types.types import QuerySourceTier
from hassette.web.dependencies import SOURCE_TIER_PARAM, SchedulerDep, TelemetryDep, db_degrades_to
from hassette.web.models import JobTriggerResponse
from hassette.web.utils import enrich_jobs_with_live_heap

router = APIRouter(prefix="/scheduler", tags=["scheduler"])


@router.get("/jobs", response_model=list[JobSummary])
async def all_jobs(
    telemetry: TelemetryDep,
    scheduler_service: SchedulerDep,
    response: Response,
    since: float | None = Query(default=None),  # pyright: ignore[reportCallInDefaultInitializer]
    source_tier: QuerySourceTier = SOURCE_TIER_PARAM,
) -> list[JobSummary]:
    """All scheduled jobs across all apps, enriched with live heap data.

    Live fields (``next_run``, ``fire_at``, ``jitter``) are joined
    from the live scheduler heap by ``db_id``.  On heap failure the DB rows are
    returned without enrichment (degraded but functional; logged warning, no 500).

    The heap snapshot is taken once — not per app — to avoid fan-out overhead.
    """
    jobs: list[JobSummary] = []
    with db_degrades_to(response):
        db_jobs = list(await telemetry.get_job_summary(since=since, source_tier=source_tier))
        jobs = await enrich_jobs_with_live_heap(db_jobs, scheduler_service, context="global enrichment")
    return jobs


@router.post(
    "/jobs/{job_id}/trigger",
    status_code=202,
    response_model=JobTriggerResponse,
    responses={409: {"description": "Job is not currently triggerable or is already executing"}},
)
async def trigger_job(job_id: int, scheduler_service: SchedulerDep) -> JobTriggerResponse:
    """Manually trigger a scheduled job to run immediately.

    Looks up the job on the live scheduler heap by ``job_id`` (the job's ``db_id``). Returns
    202 and dispatches the job through the same ``run_job_with_guard()`` path as a scheduled
    fire, recording the execution with ``trigger_mode="manual"``. Returns 409 when the job
    is not currently triggerable (already fired, mid-execution from its scheduled fire, or its
    owning app is not running) or when a ``SINGLE``-mode job is currently executing.

    A still-pending one-shot job (``After``/``Once`` trigger) is dequeued from the heap
    before dispatch to prevent a second scheduled fire at its original time.
    """
    try:
        job = await scheduler_service.trigger_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if job.mode is ExecutionMode.SINGLE and job.guard.is_running():
        raise HTTPException(status_code=409, detail="Job is currently executing")

    if job.trigger is None or job.trigger.next_run_time(job.next_run, date_utils.now()) is None:
        scheduler_service.dequeue_job(job)

    scheduler_service.task_bucket.spawn(
        scheduler_service.run_job_with_guard(job, trigger_mode="manual"),
        name="scheduler:manual_trigger",
    )

    return JobTriggerResponse(status="accepted", job_id=job_id, job_name=job.name)
