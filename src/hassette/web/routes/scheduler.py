"""Global scheduler jobs endpoint for the Hassette Web API.

Returns all scheduled jobs across all apps, enriched with live heap data.
"""

from logging import getLogger

from fastapi import APIRouter, Query, Response

from hassette.core.telemetry_models import JobSummary
from hassette.types.types import QuerySourceTier
from hassette.web.dependencies import SOURCE_TIER_PARAM, SchedulerDep, TelemetryDep
from hassette.web.routes.telemetry import DB_ERRORS
from hassette.web.utils import enrich_jobs_with_heap

LOGGER = getLogger(__name__)

router = APIRouter(prefix="/scheduler", tags=["scheduler"])


@router.get("/jobs", response_model=list[JobSummary])
async def all_jobs(
    telemetry: TelemetryDep,
    scheduler_service: SchedulerDep,
    response: Response,
    since: float | None = Query(default=None),  # pyright: ignore[reportCallInDefaultInitializer]
    source_tier: QuerySourceTier | None = SOURCE_TIER_PARAM,
) -> list[JobSummary]:
    """All scheduled jobs across all apps, enriched with live heap data.

    Live fields (``next_run``, ``fire_at``, ``jitter``, ``cancelled``) are joined
    from the live scheduler heap by ``db_id``.  On heap failure the DB rows are
    returned without enrichment (degraded but functional; logged warning, no 500).

    The heap snapshot is taken once — not per app — to avoid fan-out overhead.
    """
    effective_tier = source_tier if source_tier is not None else "all"
    try:
        db_jobs = list(await telemetry.get_all_jobs_summary(since=since, source_tier=effective_tier))
    except DB_ERRORS:
        LOGGER.warning("Failed to fetch global job summaries", exc_info=True)
        response.status_code = 503
        return []

    # Single heap snapshot, never per-app.
    try:
        live_jobs = await scheduler_service.get_all_jobs()
    except (OSError, RuntimeError, ValueError):
        LOGGER.warning(
            "Failed to fetch live scheduler jobs for global enrichment; returning DB rows only", exc_info=True
        )
        return db_jobs

    return enrich_jobs_with_heap(db_jobs, live_jobs)
