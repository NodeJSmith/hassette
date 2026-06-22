"""Global scheduler jobs endpoint for the Hassette Web API.

Returns all scheduled jobs across all apps, enriched with live heap data.
"""

from fastapi import APIRouter, Query, Response

from hassette.schemas.telemetry_models import JobSummary
from hassette.types.types import QuerySourceTier
from hassette.web.dependencies import SOURCE_TIER_PARAM, SchedulerDep, TelemetryDep, db_degrades_to
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
