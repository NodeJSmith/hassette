"""JSON telemetry endpoints for the Preact SPA.

Time-window filtering is client-driven: endpoints accept an optional ``since``
query parameter (Unix epoch float).  Pass a ``since`` value to restrict results
to records with ``execution_start_ts >= since``, or omit it for all-time aggregates.
"""

import time
from logging import getLogger
from typing import Literal, cast

from fastapi import APIRouter, Path, Query, Response

from hassette.const.misc import SECONDS_PER_DAY
from hassette.exceptions import TelemetryUnavailableError
from hassette.schemas.query_constants import DEFAULT_QUERY_LIMIT, DEFAULT_SPARKLINE_BUCKETS, MAX_QUERY_LIMIT
from hassette.schemas.telemetry_models import (
    ActivityFeedEntry,
    AppHealthSummary,
    AppLastError,
    Execution,
    JobSummary,
)
from hassette.types.types import QuerySourceTier
from hassette.web.dependencies import (
    SOURCE_TIER_PARAM,
    HassetteDep,
    RuntimeDep,
    SchedulerDep,
    TelemetryDep,
    db_degrades_to,
)
from hassette.web.mappers import to_listener_with_summary
from hassette.web.models import (
    ActivityBucket,
    AppHealthResponse,
    DashboardAppGridEntry,
    DashboardAppGridResponse,
    HealthStatus,
    ListenerWithSummary,
    ManifestStatus,
    TelemetryStatusResponse,
)
from hassette.web.telemetry_helpers import (
    classify_error_rate,
    classify_health_bar,
    compute_error_rate,
    compute_success_rate,
)
from hassette.web.utils import enrich_jobs_with_live_heap

LOGGER = getLogger(__name__)

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


@router.get(
    "/status",
    response_model=TelemetryStatusResponse,
    responses={503: {"model": TelemetryStatusResponse}},
)
async def telemetry_status(
    hassette: HassetteDep,
    telemetry: TelemetryDep,
    response: Response,
) -> TelemetryStatusResponse:
    """Health check for the telemetry database.

    Runs a representative query against the unified ``executions`` table.
    Returns 503 with ``degraded: true`` when the database is
    unavailable; 200 with ``degraded: false`` when healthy.
    """
    result: TelemetryStatusResponse = TelemetryStatusResponse(degraded=True)
    with db_degrades_to(response):
        await telemetry.check_health()
        try:
            overflow, exhausted, shutdown = hassette.get_drop_counters()
        except (AttributeError, RuntimeError):
            overflow, exhausted, shutdown = 0, 0, 0
        try:
            error_handler_failures = hassette.get_error_handler_failures()
        except (AttributeError, RuntimeError):
            error_handler_failures = 0
        result = TelemetryStatusResponse(
            degraded=False,
            dropped_overflow=overflow,
            dropped_exhausted=exhausted,
            dropped_shutdown=shutdown,
            error_handler_failures=error_handler_failures,
        )
    return result


def error_rate_from_summary(summary: AppHealthSummary) -> float:
    """Compute error rate percentage from an app health summary."""
    return compute_error_rate(
        total_invocations=summary.total_invocations,
        total_executions=summary.total_executions,
        handler_errors=summary.total_errors + summary.total_timed_out,
        job_errors=summary.total_job_errors + summary.total_job_timed_out,
    )


def health_status_from_summary(summary: AppHealthSummary) -> HealthStatus:
    """Derive a health status label from an app health summary.

    Zero-invocation apps have a ``0.0`` error rate, so they classify as
    ``"excellent"`` — the ``HealthStatus`` Literal has no ``"unknown"`` state.
    """
    success_rate = compute_success_rate(error_rate_from_summary(summary))
    return classify_health_bar(success_rate)


INSTANCE_INDEX_PARAM = Query(  # pyright: ignore[reportCallInDefaultInitializer]
    default=0,
    description="App instance index. Defaults to 0. Multi-instance apps have indices 0..N-1.",
)

APP_KEY_PARAM = Path(  # pyright: ignore[reportCallInDefaultInitializer]
    description="Use `__hassette__` to query framework-internal actor telemetry.",
)


@router.get("/app/{app_key}/health", response_model=AppHealthResponse)
async def app_health(
    telemetry: TelemetryDep,
    response: Response,
    app_key: str = APP_KEY_PARAM,  # pyright: ignore[reportCallInDefaultInitializer]
    instance_index: int = INSTANCE_INDEX_PARAM,
    since: float | None = Query(default=None),  # pyright: ignore[reportCallInDefaultInitializer]
    source_tier: QuerySourceTier = SOURCE_TIER_PARAM,
) -> AppHealthResponse:
    """Health strip metrics for a single app instance."""
    result: AppHealthResponse = AppHealthResponse(
        error_rate=0.0,
        error_rate_class=classify_error_rate(0.0),
        handler_avg_duration=0.0,
        job_avg_duration=0.0,
        last_activity_ts=None,
        health_status=classify_health_bar(100.0),
    )
    with db_degrades_to(response):
        agg = await telemetry.get_app_health_aggregates(
            app_key=app_key, instance_index=instance_index, since=since, source_tier=source_tier
        )
        error_rate = compute_error_rate(
            total_invocations=agg.total_invocations,
            total_executions=agg.total_executions,
            handler_errors=agg.handler_errors + agg.handler_timed_out,
            job_errors=agg.job_errors + agg.job_timed_out,
        )
        result = AppHealthResponse(
            error_rate=error_rate,
            error_rate_class=classify_error_rate(error_rate),
            handler_avg_duration=agg.handler_avg_duration_ms,
            job_avg_duration=agg.job_avg_duration_ms,
            last_activity_ts=agg.last_activity_ts,
            health_status=classify_health_bar(compute_success_rate(error_rate)),
        )
    return result


@router.get("/app/{app_key}/listeners", response_model=list[ListenerWithSummary])
async def app_listeners(
    telemetry: TelemetryDep,
    hassette: HassetteDep,
    response: Response,
    app_key: str = APP_KEY_PARAM,  # pyright: ignore[reportCallInDefaultInitializer]
    instance_index: int = INSTANCE_INDEX_PARAM,
    since: float | None = Query(default=None),  # pyright: ignore[reportCallInDefaultInitializer]
    source_tier: QuerySourceTier = SOURCE_TIER_PARAM,
) -> list[ListenerWithSummary]:
    """Listener metrics with human-readable handler summaries."""
    rows: list[ListenerWithSummary] = []
    with db_degrades_to(response):
        listeners = await telemetry.get_listener_summary(
            app_key=app_key, instance_index=instance_index, since=since, source_tier=source_tier
        )
        live_counts = hassette.bus_service.live_execution_counts()
        rows = [to_listener_with_summary(ls, live_counts) for ls in listeners]
    return rows


@router.get("/app/{app_key}/activity", response_model=list[ActivityFeedEntry])
async def app_activity(
    telemetry: TelemetryDep,
    response: Response,
    app_key: str = APP_KEY_PARAM,  # pyright: ignore[reportCallInDefaultInitializer]
    instance_index: int | None = Query(
        default=None, description="App instance index. None returns activity across all instances."
    ),  # pyright: ignore[reportCallInDefaultInitializer]
    limit: int = Query(default=DEFAULT_QUERY_LIMIT, ge=1, le=MAX_QUERY_LIMIT),  # pyright: ignore[reportCallInDefaultInitializer]
    since: float | None = Query(default=None),  # pyright: ignore[reportCallInDefaultInitializer]
    source_tier: QuerySourceTier = SOURCE_TIER_PARAM,
) -> list[ActivityFeedEntry]:
    """Recent handler invocations and job executions for a single app, merged and sorted by time."""
    effective_since = since if since is not None else time.time() - SECONDS_PER_DAY
    activity: list[ActivityFeedEntry] = []
    with db_degrades_to(response):
        activity = await telemetry.get_app_recent_activity(
            app_key=app_key,
            instance_index=instance_index,
            limit=limit,
            since=effective_since,
            source_tier=source_tier,
        )
    return activity


@router.get("/app/{app_key}/jobs", response_model=list[JobSummary])
async def app_jobs(
    telemetry: TelemetryDep,
    scheduler_service: SchedulerDep,
    response: Response,
    app_key: str = APP_KEY_PARAM,  # pyright: ignore[reportCallInDefaultInitializer]
    instance_index: int = INSTANCE_INDEX_PARAM,
    since: float | None = Query(default=None),  # pyright: ignore[reportCallInDefaultInitializer]
    source_tier: QuerySourceTier = SOURCE_TIER_PARAM,
) -> list[JobSummary]:
    """Job summaries for a single app instance, enriched with live heap data.

    Live fields (``next_run``, ``fire_at``, ``jitter``) are joined
    from the live scheduler heap by ``db_id``. On heap failure the DB rows are
    returned without enrichment (degraded but functional; logged warning, no 500).
    """
    jobs: list[JobSummary] = []
    with db_degrades_to(response):
        db_jobs = list(
            await telemetry.get_job_summary(
                app_key=app_key, instance_index=instance_index, since=since, source_tier=source_tier
            )
        )
        jobs = await enrich_jobs_with_live_heap(db_jobs, scheduler_service)
    return jobs


@router.get("/executions", response_model=list[Execution])
async def list_executions(
    telemetry: TelemetryDep,
    response: Response,
    kind: Literal["handler", "job"] | None = Query(default=None, description="Filter by kind: 'handler' or 'job'."),  # pyright: ignore[reportCallInDefaultInitializer]
    limit: int = Query(default=DEFAULT_QUERY_LIMIT, ge=1, le=MAX_QUERY_LIMIT),  # pyright: ignore[reportCallInDefaultInitializer]
    since: float | None = Query(default=None),  # pyright: ignore[reportCallInDefaultInitializer]
) -> list[Execution]:
    """Combined execution list (handler invocations and job executions).

    Filter by ``kind=handler`` or ``kind=job`` to restrict to one type.
    Each record includes a ``kind`` field that discriminates the execution type.
    """
    executions: list[Execution] = []
    with db_degrades_to(response):
        executions = await telemetry.get_executions(kind=kind, limit=limit, since=since)
    return executions


@router.get("/listener/{listener_id}/executions", response_model=list[Execution])
async def listener_executions(
    listener_id: int,
    telemetry: TelemetryDep,
    response: Response,
    limit: int = Query(default=DEFAULT_QUERY_LIMIT, ge=1, le=MAX_QUERY_LIMIT),  # pyright: ignore[reportCallInDefaultInitializer]
    since: float | None = Query(default=None),  # pyright: ignore[reportCallInDefaultInitializer]
) -> list[Execution]:
    """Execution history for a specific listener (handler invocations)."""
    executions: list[Execution] = []
    with db_degrades_to(response):
        executions = await telemetry.get_executions(listener_id=listener_id, limit=limit, since=since)
    return executions


@router.get("/job/{job_id}/executions", response_model=list[Execution])
async def job_executions(
    job_id: int,
    telemetry: TelemetryDep,
    response: Response,
    limit: int = Query(default=DEFAULT_QUERY_LIMIT, ge=1, le=MAX_QUERY_LIMIT),  # pyright: ignore[reportCallInDefaultInitializer]
    since: float | None = Query(default=None),  # pyright: ignore[reportCallInDefaultInitializer]
) -> list[Execution]:
    """Execution history for a specific job."""
    executions: list[Execution] = []
    with db_degrades_to(response):
        executions = await telemetry.get_executions(job_id=job_id, limit=limit, since=since)
    return executions


@router.get("/dashboard/app-grid", response_model=DashboardAppGridResponse)
async def dashboard_app_grid(
    runtime: RuntimeDep,
    telemetry: TelemetryDep,
    since: float | None = Query(default=None),  # pyright: ignore[reportCallInDefaultInitializer]
) -> DashboardAppGridResponse:
    """Per-app health data for the dashboard grid.

    Always uses ``source_tier='app'`` — framework actors are shown via FrameworkHealth,
    not the manifest-driven app grid.
    """
    snapshot = runtime.get_all_manifests_snapshot()
    try:
        summaries = await telemetry.get_all_app_summaries(since=since, source_tier="app")
    except TelemetryUnavailableError:
        LOGGER.warning("Failed to fetch app summaries for dashboard grid", exc_info=True)
        summaries = {}

    per_app_buckets: dict[str, list[tuple[int, int]]] = {}
    per_app_errors: dict[str, AppLastError] = {}
    if since is not None:
        now = time.time()
        try:
            per_app_buckets = await telemetry.get_per_app_activity_buckets(
                since,
                now,
                num_buckets=DEFAULT_SPARKLINE_BUCKETS,
                source_tier="app",
            )
        except TelemetryUnavailableError:
            LOGGER.warning("Failed to fetch per-app activity buckets", exc_info=True)
        try:
            per_app_errors = await telemetry.get_per_app_last_errors(since=since, source_tier="app")
        except TelemetryUnavailableError:
            LOGGER.warning("Failed to fetch per-app last errors", exc_info=True)

    empty = AppHealthSummary(
        handler_count=0,
        job_count=0,
        total_invocations=0,
        total_errors=0,
        total_timed_out=0,
        total_executions=0,
        total_job_errors=0,
        total_job_timed_out=0,
        avg_duration_ms=0.0,
        last_activity_ts=None,
    )

    entries: list[DashboardAppGridEntry] = []
    for manifest in snapshot.manifests:
        health = summaries.get(manifest.app_key, empty)
        rate = error_rate_from_summary(health)
        buckets = per_app_buckets.get(manifest.app_key, [])
        err_info = per_app_errors.get(manifest.app_key)
        entries.append(
            DashboardAppGridEntry(
                app_key=manifest.app_key,
                status=cast("ManifestStatus", manifest.status),  # AppManifestInfo.status is str
                display_name=manifest.display_name,
                instance_count=manifest.instance_count,
                handler_count=health.handler_count,
                job_count=health.job_count,
                total_invocations=health.total_invocations,
                total_errors=health.total_errors,
                total_timed_out=health.total_timed_out,
                total_executions=health.total_executions,
                total_job_errors=health.total_job_errors,
                total_job_timed_out=health.total_job_timed_out,
                avg_duration_ms=health.avg_duration_ms,
                last_activity_ts=health.last_activity_ts,
                health_status=health_status_from_summary(health),
                error_rate=rate,
                error_rate_class=classify_error_rate(rate),
                last_error_message=err_info.error_message if err_info else None,
                last_error_type=err_info.error_type if err_info else None,
                last_error_ts=err_info.timestamp if err_info else None,
                activity_buckets=[ActivityBucket(ok=ok, err=err) for ok, err in buckets],
            )
        )

    return DashboardAppGridResponse(apps=entries)
