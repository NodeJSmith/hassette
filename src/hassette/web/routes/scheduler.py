"""Global scheduler jobs endpoint for the Hassette Web API.

Returns all scheduled jobs across all apps, enriched with live heap data.
"""

from logging import getLogger

from fastapi import APIRouter, Query, Response

from hassette.schemas.telemetry_models import JobSummary
from hassette.types.types import QuerySourceTier
from hassette.web.dependencies import DB_ERRORS, SOURCE_TIER_PARAM, SchedulerDep, TelemetryDep
from hassette.web.utils import enrich_jobs_with_live_heap

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
    """All scheduled jobs across all apps, enriched with live heap data.

    Live fields (``next_run``, ``fire_at``, ``jitter``) are joined
    from the live scheduler heap by ``db_id``.  On heap failure the DB rows are
    returned without enrichment (degraded but functional; logged warning, no 500).

    The heap snapshot is taken once — not per app — to avoid fan-out overhead.
    """
    try:
        db_jobs = list(await telemetry.get_all_jobs_summary(since=since, source_tier=source_tier))
    except DB_ERRORS:
        LOGGER.warning("Failed to fetch global job summaries", exc_info=True)
        response.status_code = 503
        return []

    return await enrich_jobs_with_live_heap(db_jobs, scheduler_service, context="global enrichment")
