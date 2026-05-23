"""JSON telemetry endpoints for the Preact SPA.

Time-window filtering is client-driven: endpoints accept an optional ``since``
query parameter (Unix epoch float).  Pass a ``since`` value to restrict results
to records with ``execution_start_ts >= since``, or omit it for all-time aggregates.
"""

import sqlite3
import time
from logging import getLogger
from typing import cast

from fastapi import APIRouter, Path, Query, Response

from hassette.const.misc import SECONDS_PER_DAY
from hassette.core.telemetry_models import (
    ActivityFeedEntry,
    AppHealthSummary,
    AppLastError,
    HandlerInvocation,
    JobExecution,
    JobSummary,
)
from hassette.types.types import QuerySourceTier
from hassette.web.dependencies import SOURCE_TIER_PARAM, HassetteDep, RuntimeDep, SchedulerDep, TelemetryDep
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
)
from hassette.web.utils import enrich_jobs_with_heap

LOGGER = getLogger(__name__)

DB_ERRORS: tuple[type[Exception], ...] = (sqlite3.Error, OSError, ValueError)
"""Database error types to catch in telemetry endpoints.

Includes ``ValueError`` because aiosqlite raises it for closed-connection
errors during shutdown.  All three types are suppressed uniformly — a degraded
response is always preferable to an unhandled 500."""

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

    Runs a representative query exercising the listeners -> handler_invocations
    join path. Returns 503 with ``degraded: true`` when the database is
    unavailable; 200 with ``degraded: false`` when healthy.
    """
    try:
        await telemetry.check_health()
    except DB_ERRORS:
        LOGGER.warning("Telemetry database health check failed", exc_info=True)
        response.status_code = 503
        return TelemetryStatusResponse(degraded=True)

    try:
        overflow, exhausted, no_session, shutdown = hassette.get_drop_counters()
    except (AttributeError, RuntimeError):
        overflow, exhausted, no_session, shutdown = 0, 0, 0, 0

    try:
        error_handler_failures = hassette.get_error_handler_failures()
    except (AttributeError, RuntimeError):
        error_handler_failures = 0

    return TelemetryStatusResponse(
        degraded=False,
        dropped_overflow=overflow,
        dropped_exhausted=exhausted,
        dropped_no_session=no_session,
        dropped_shutdown=shutdown,
        error_handler_failures=error_handler_failures,
    )


def _health_status_from_summary(summary: AppHealthSummary) -> HealthStatus:
    """Derive a health status label from an app health summary.

    Zero-invocation apps return ``"excellent"`` — consistent with the 503
    fallback path at line ~143 and the ``HealthStatus`` Literal (no ``"unknown"``).
    """
    total = summary.total_invocations + summary.total_executions
    if total == 0:
        return "excellent"
    failures = summary.total_errors + summary.total_timed_out + summary.total_job_errors + summary.total_job_timed_out
    success_rate = ((total - failures) / total) * 100
    return classify_health_bar(success_rate)


def _error_rate_from_summary(summary: AppHealthSummary) -> float:
    """Compute error rate percentage from an app health summary."""
    return compute_error_rate(
        total_invocations=summary.total_invocations,
        total_executions=summary.total_executions,
        handler_errors=summary.total_errors + summary.total_timed_out,
        job_errors=summary.total_job_errors + summary.total_job_timed_out,
    )


_INSTANCE_INDEX_PARAM = Query(  # pyright: ignore[reportCallInDefaultInitializer]
    default=0,
    description="App instance index. Defaults to 0. Multi-instance apps have indices 0..N-1.",
)


@router.get("/app/{app_key}/health", response_model=AppHealthResponse)
async def app_health(
    telemetry: TelemetryDep,
    response: Response,
    app_key: str = Path(description="Use `__hassette__` to query framework-internal actor telemetry."),  # pyright: ignore[reportCallInDefaultInitializer]
    instance_index: int = _INSTANCE_INDEX_PARAM,
    since: float | None = Query(default=None),  # pyright: ignore[reportCallInDefaultInitializer]
    source_tier: QuerySourceTier | None = SOURCE_TIER_PARAM,
) -> AppHealthResponse:
    """Health strip metrics for a single app instance."""
    effective_tier = source_tier if source_tier is not None else "app"
    try:
        listeners = await telemetry.get_listener_summary(
            app_key=app_key, instance_index=instance_index, since=since, source_tier=effective_tier
        )
        jobs = await telemetry.get_job_summary(
            app_key=app_key, instance_index=instance_index, since=since, source_tier=effective_tier
        )
    except DB_ERRORS:
        LOGGER.warning("Failed to fetch app health for %s", app_key, exc_info=True)
        response.status_code = 503
        return AppHealthResponse(
            error_rate=0.0,
            error_rate_class=classify_error_rate(0.0),
            handler_avg_duration=0.0,
            job_avg_duration=0.0,
            last_activity_ts=None,
            health_status=classify_health_bar(100.0),
        )

    total_invocations = sum(ls.total_invocations for ls in listeners)
    total_executions = sum(j.total_executions for j in jobs)
    handler_errors = sum(ls.failed + ls.timed_out for ls in listeners)
    job_errors = sum(j.failed + j.timed_out for j in jobs)
    error_rate = compute_error_rate(
        total_invocations=total_invocations,
        total_executions=total_executions,
        handler_errors=handler_errors,
        job_errors=job_errors,
    )
    total = total_invocations + total_executions
    errors = handler_errors + job_errors
    success_rate = ((total - errors) / total * 100) if total > 0 else 100.0

    # Compute handler/job-specific averages
    total_handler_inv = sum(ls.total_invocations for ls in listeners)
    handler_avg = (sum(ls.total_duration_ms for ls in listeners) / total_handler_inv) if total_handler_inv > 0 else 0.0
    total_job_exec = sum(j.total_executions for j in jobs)
    job_avg = (sum(j.total_duration_ms for j in jobs) / total_job_exec) if total_job_exec > 0 else 0.0

    last_times: list[float] = [ls.last_invoked_at for ls in listeners if ls.last_invoked_at is not None]
    last_times.extend(j.last_executed_at for j in jobs if j.last_executed_at is not None)

    return AppHealthResponse(
        error_rate=error_rate,
        error_rate_class=classify_error_rate(error_rate),
        handler_avg_duration=handler_avg,
        job_avg_duration=job_avg,
        last_activity_ts=max(last_times) if last_times else None,
        health_status=classify_health_bar(success_rate),
    )


@router.get("/app/{app_key}/listeners", response_model=list[ListenerWithSummary])
async def app_listeners(
    telemetry: TelemetryDep,
    response: Response,
    app_key: str = Path(description="Use `__hassette__` to query framework-internal actor telemetry."),  # pyright: ignore[reportCallInDefaultInitializer]
    instance_index: int = _INSTANCE_INDEX_PARAM,
    since: float | None = Query(default=None),  # pyright: ignore[reportCallInDefaultInitializer]
    source_tier: QuerySourceTier | None = SOURCE_TIER_PARAM,
) -> list[ListenerWithSummary]:
    """Listener metrics with human-readable handler summaries."""
    effective_tier = source_tier if source_tier is not None else "app"
    try:
        listeners = await telemetry.get_listener_summary(
            app_key=app_key, instance_index=instance_index, since=since, source_tier=effective_tier
        )
    except DB_ERRORS:
        LOGGER.warning("Failed to fetch listeners for %s", app_key, exc_info=True)
        response.status_code = 503
        return []
    return [to_listener_with_summary(ls) for ls in listeners]


@router.get("/app/{app_key}/activity", response_model=list[ActivityFeedEntry])
async def app_activity(
    telemetry: TelemetryDep,
    response: Response,
    app_key: str = Path(description="Use `__hassette__` to query framework-internal actor telemetry."),  # pyright: ignore[reportCallInDefaultInitializer]
    instance_index: int | None = Query(
        default=None, description="App instance index. None returns activity across all instances."
    ),  # pyright: ignore[reportCallInDefaultInitializer]
    limit: int = Query(default=50, ge=1, le=500),  # pyright: ignore[reportCallInDefaultInitializer]
    since: float | None = Query(default=None),  # pyright: ignore[reportCallInDefaultInitializer]
    source_tier: QuerySourceTier | None = SOURCE_TIER_PARAM,
) -> list[ActivityFeedEntry]:
    """Recent handler invocations and job executions for a single app, merged and sorted by time."""
    effective_tier = source_tier if source_tier is not None else "app"
    effective_since = since if since is not None else time.time() - SECONDS_PER_DAY
    try:
        return await telemetry.get_app_recent_activity(
            app_key=app_key,
            instance_index=instance_index,
            limit=limit,
            since=effective_since,
            source_tier=effective_tier,
        )
    except DB_ERRORS:
        LOGGER.warning("Failed to fetch activity for %s", app_key, exc_info=True)
        response.status_code = 503
        return []


@router.get("/app/{app_key}/jobs", response_model=list[JobSummary])
async def app_jobs(
    telemetry: TelemetryDep,
    scheduler_service: SchedulerDep,
    response: Response,
    app_key: str = Path(description="Use `__hassette__` to query framework-internal actor telemetry."),  # pyright: ignore[reportCallInDefaultInitializer]
    instance_index: int = _INSTANCE_INDEX_PARAM,
    since: float | None = Query(default=None),  # pyright: ignore[reportCallInDefaultInitializer]
    source_tier: QuerySourceTier | None = SOURCE_TIER_PARAM,
) -> list[JobSummary]:
    """Job summaries for a single app instance, enriched with live heap data.

    Live fields (``next_run``, ``fire_at``, ``jitter``) are joined
    from the live scheduler heap by ``db_id``. On heap failure the DB rows are
    returned without enrichment (degraded but functional; logged warning, no 500).
    """
    effective_tier = source_tier if source_tier is not None else "app"
    try:
        db_jobs = list(
            await telemetry.get_job_summary(
                app_key=app_key, instance_index=instance_index, since=since, source_tier=effective_tier
            )
        )
    except DB_ERRORS:
        LOGGER.warning("Failed to fetch jobs for %s", app_key, exc_info=True)
        response.status_code = 503
        return []

    # Enrich DB rows with live heap state. INVARIANT: get_all_jobs() acquires
    # FairAsyncRLock internally and returns a list copy.
    try:
        live_jobs = await scheduler_service.get_all_jobs()
    except (OSError, RuntimeError, ValueError):
        LOGGER.warning("Failed to fetch live scheduler jobs for enrichment; returning DB rows only", exc_info=True)
        return db_jobs

    return enrich_jobs_with_heap(db_jobs, live_jobs)


@router.get("/handler/{listener_id}/invocations", response_model=list[HandlerInvocation])
async def handler_invocations(
    listener_id: int,
    telemetry: TelemetryDep,
    response: Response,
    limit: int = Query(default=50, ge=1, le=500),  # pyright: ignore[reportCallInDefaultInitializer]
    since: float | None = Query(default=None),  # pyright: ignore[reportCallInDefaultInitializer]
) -> list[HandlerInvocation]:
    """Invocation history for a specific handler."""
    try:
        return list(await telemetry.get_handler_invocations(listener_id=listener_id, limit=limit, since=since))
    except DB_ERRORS:
        LOGGER.warning("Failed to fetch invocations for listener %s", listener_id, exc_info=True)
        response.status_code = 503
        return []


@router.get("/job/{job_id}/executions", response_model=list[JobExecution])
async def job_executions(
    job_id: int,
    telemetry: TelemetryDep,
    response: Response,
    limit: int = Query(default=50, ge=1, le=500),  # pyright: ignore[reportCallInDefaultInitializer]
    since: float | None = Query(default=None),  # pyright: ignore[reportCallInDefaultInitializer]
) -> list[JobExecution]:
    """Execution history for a specific job."""
    try:
        return list(await telemetry.get_job_executions(job_id=job_id, limit=limit, since=since))
    except DB_ERRORS:
        LOGGER.warning("Failed to fetch executions for job %s", job_id, exc_info=True)
        response.status_code = 503
        return []


_NUM_SPARKLINE_BUCKETS = 12


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
    except DB_ERRORS:
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
                num_buckets=12,
                source_tier="app",
            )
        except DB_ERRORS:
            LOGGER.warning("Failed to fetch per-app activity buckets", exc_info=True)
        try:
            per_app_errors = await telemetry.get_per_app_last_errors(since=since, source_tier="app")
        except DB_ERRORS:
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

    entries = []
    for manifest in snapshot.manifests:
        health = summaries.get(manifest.app_key, empty)
        rate = _error_rate_from_summary(health)
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
                health_status=_health_status_from_summary(health),
                error_rate=rate,
                error_rate_class=classify_error_rate(rate),
                last_error_message=err_info.error_message if err_info else None,
                last_error_type=err_info.error_type if err_info else None,
                last_error_ts=err_info.timestamp if err_info else None,
                activity_buckets=[ActivityBucket(ok=ok, err=err) for ok, err in buckets],
            )
        )

    return DashboardAppGridResponse(apps=entries)
