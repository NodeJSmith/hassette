"""Global scheduler jobs endpoint for the Hassette Web API.

Returns all scheduled jobs across all apps, enriched with live registry data.
"""

from logging import getLogger

from fastapi import APIRouter, HTTPException, Query, Request, Response

from hassette.exceptions import JobRemovedError
from hassette.schemas.job_models import JobSummary
from hassette.types.types import QuerySourceTier
from hassette.web.auth import peer_address_or_unknown
from hassette.web.dependencies import SOURCE_TIER_PARAM, SchedulerDep, TelemetryDep, db_degrades_to
from hassette.web.models import JobTriggerResponse
from hassette.web.utils import enrich_jobs_with_live_data

LOGGER = getLogger(__name__)

router = APIRouter(prefix="/scheduler", tags=["scheduler"])


@router.get("/jobs", response_model=list[JobSummary])
async def all_jobs(
    telemetry: TelemetryDep,
    scheduler_service: SchedulerDep,
    response: Response,
    since: float | None = Query(default=None),  # pyright: ignore[reportCallInDefaultInitializer]
    source_tier: QuerySourceTier = SOURCE_TIER_PARAM,
) -> list[JobSummary]:
    """All scheduled jobs across all apps, enriched with live registry data.

    ``schedule_status``/``schedule_status_reason`` and, for ``SCHEDULED`` jobs, live timing
    (``next_run``, ``fire_at``, ``jitter``) are joined from the live scheduler registry by
    ``db_id``. On registry failure the DB rows are returned without enrichment (degraded but
    functional; logged warning, no 500).

    The registry snapshot is taken once — not per app — to avoid fan-out overhead.
    """
    jobs: list[JobSummary] = []
    with db_degrades_to(response):
        db_jobs = list(await telemetry.get_job_summary(since=since, source_tier=source_tier))
        jobs = await enrich_jobs_with_live_data(db_jobs, scheduler_service, context="global enrichment")
    return jobs


@router.post(
    "/jobs/{job_id}/trigger",
    status_code=202,
    response_model=JobTriggerResponse,
    responses={409: {"description": "Job is not currently registered (no live registration)"}},
)
async def trigger_job(job_id: int, scheduler_service: SchedulerDep, request: Request) -> JobTriggerResponse:
    """Manually submit a job for immediate execution.

    Resolves the job by ``job_id`` (the job's ``db_id``) in the live scheduler registry, then
    submits it through the same ``SchedulerService.submit_job()`` path used by ``Job.submit()``
    — fire-and-observe, dispatched via ``run_job_with_guard(job, trigger_mode="manual")``.

    A live registration always returns 202 accepted, even when overlap policy (``single``
    mode, queue capacity) later suppresses or drops the invocation — those outcomes are
    decided asynchronously by the job's existing guard and are not previewed here. Returns
    409 when the job has no live registration: never registered, or removed via
    ``Job.remove()``, ``Scheduler.remove_job()``/``remove_group()``, owner shutdown, or
    ``if_exists="replace"`` since the caller last saw it.

    Manual submission never consumes, moves, or completes a pending automatic occurrence —
    a pending one-shot or recurring schedule still fires at its own time.
    """
    try:
        job = await scheduler_service.trigger_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    try:
        scheduler_service.submit_job(job)
    except JobRemovedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    LOGGER.info("Triggered job %s (%s) (source=%s)", job_id, job.name, peer_address_or_unknown(request))
    return JobTriggerResponse(status="accepted", job_id=job_id, job_name=job.name)
