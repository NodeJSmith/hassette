"""JSON telemetry endpoints for the Preact SPA.

Session scoping is client-driven: endpoints accept an optional ``session_id``
query parameter.  Pass a session ID for current-session data, or omit it for
all-time aggregates.
"""

import sqlite3
import time
from logging import getLogger

from fastapi import APIRouter, Path, Query, Response

from hassette.core.telemetry_models import (
    AppHealthSummary,
    HandlerErrorRecord,
    HandlerInvocation,
    JobErrorRecord,
    JobExecution,
    JobSummary,
    SessionRecord,
)
from hassette.types.types import QuerySourceTier
from hassette.web.dependencies import HassetteDep, RuntimeDep, SchedulerDep, TelemetryDep
from hassette.web.mappers import to_listener_with_summary
from hassette.web.models import (
    AppHealthResponse,
    DashboardAppGridEntry,
    DashboardAppGridResponse,
    DashboardErrorsResponse,
    DashboardKpisResponse,
    FrameworkSummaryResponse,
    HandlerErrorEntry,
    JobErrorEntry,
    ListenerWithSummary,
    SessionListEntry,
    TelemetryStatusResponse,
)
from hassette.web.telemetry_helpers import (
    classify_error_rate,
    classify_health_bar,
)

LOGGER = getLogger(__name__)

DB_ERRORS: tuple[type[Exception], ...] = (sqlite3.Error, OSError, ValueError)
"""Database error types to catch in telemetry endpoints.

Includes ``ValueError`` because aiosqlite raises it for closed-connection
errors during shutdown.  All three types are suppressed uniformly — a degraded
response is always preferable to an unhandled 500."""

_SOURCE_TIER_PARAM = Query(
    default=None,
    description="Filter by source tier. 'app' excludes framework internals. "
    "'framework' returns only internal actors. 'all' returns everything.",
)

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

    return TelemetryStatusResponse(
        degraded=False,
        dropped_overflow=overflow,
        dropped_exhausted=exhausted,
        dropped_no_session=no_session,
        dropped_shutdown=shutdown,
    )


@router.get("/sessions", response_model=list[SessionListEntry])
async def sessions(
    telemetry: TelemetryDep,
    limit: int = Query(default=50, ge=1, le=200),  # pyright: ignore[reportCallInDefaultInitializer]
) -> list[SessionRecord]:
    """List recent sessions with lifecycle data."""
    try:
        return list(await telemetry.get_session_list(limit=limit))
    except DB_ERRORS:
        LOGGER.warning("Failed to fetch session list", exc_info=True)
        return []


def _health_status_from_summary(summary: AppHealthSummary) -> str:
    """Derive a health status label from an app health summary."""
    total = summary.total_invocations + summary.total_executions
    errors = summary.total_errors + summary.total_job_errors
    if total == 0:
        return "unknown"
    success_rate = ((total - errors) / total) * 100
    return classify_health_bar(success_rate)


def _error_rate_from_summary(summary: AppHealthSummary) -> float:
    """Compute error rate percentage from an app health summary."""
    total = summary.total_invocations + summary.total_executions
    if total == 0:
        return 0.0
    errors = summary.total_errors + summary.total_job_errors
    return (errors / total) * 100


@router.get("/app/{app_key}/health", response_model=AppHealthResponse)
async def app_health(
    telemetry: TelemetryDep,
    response: Response,
    app_key: str = Path(description="Use `__hassette__` to query framework-internal actor telemetry."),  # pyright: ignore[reportCallInDefaultInitializer]
    instance_index: int = 0,
    session_id: int | None = Query(default=None),  # pyright: ignore[reportCallInDefaultInitializer]
    source_tier: QuerySourceTier | None = _SOURCE_TIER_PARAM,
) -> AppHealthResponse:
    """Health strip metrics for a single app instance."""
    effective_tier = source_tier if source_tier is not None else "app"
    try:
        listeners = await telemetry.get_listener_summary(
            app_key=app_key, instance_index=instance_index, session_id=session_id, source_tier=effective_tier
        )
        jobs = await telemetry.get_job_summary(
            app_key=app_key, instance_index=instance_index, session_id=session_id, source_tier=effective_tier
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

    # Compute combined error rate (handlers + jobs) for consistency
    total = sum(ls.total_invocations for ls in listeners) + sum(j.total_executions for j in jobs)
    errors = sum(ls.failed for ls in listeners) + sum(j.failed for j in jobs)
    error_rate = (errors / total * 100) if total > 0 else 0.0
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
    instance_index: int = 0,
    session_id: int | None = Query(default=None),  # pyright: ignore[reportCallInDefaultInitializer]
    source_tier: QuerySourceTier | None = _SOURCE_TIER_PARAM,
) -> list[ListenerWithSummary]:
    """Listener metrics with human-readable handler summaries."""
    effective_tier = source_tier if source_tier is not None else "app"
    try:
        listeners = await telemetry.get_listener_summary(
            app_key=app_key, instance_index=instance_index, session_id=session_id, source_tier=effective_tier
        )
    except DB_ERRORS:
        LOGGER.warning("Failed to fetch listeners for %s", app_key, exc_info=True)
        response.status_code = 503
        return []
    return [to_listener_with_summary(ls) for ls in listeners]


@router.get("/app/{app_key}/jobs", response_model=list[JobSummary])
async def app_jobs(
    telemetry: TelemetryDep,
    scheduler_service: SchedulerDep,
    response: Response,
    app_key: str = Path(description="Use `__hassette__` to query framework-internal actor telemetry."),  # pyright: ignore[reportCallInDefaultInitializer]
    instance_index: int = 0,
    session_id: int | None = Query(default=None),  # pyright: ignore[reportCallInDefaultInitializer]
    source_tier: QuerySourceTier | None = _SOURCE_TIER_PARAM,
) -> list[JobSummary]:
    """Job summaries for a single app instance, enriched with live heap data.

    Live fields (``next_run``, ``fire_at``, ``jitter``, ``cancelled``) are joined
    from the live scheduler heap by ``db_id``. On heap failure the DB rows are
    returned without enrichment (degraded but functional; logged warning, no 500).
    """
    effective_tier = source_tier if source_tier is not None else "app"
    try:
        db_jobs = list(
            await telemetry.get_job_summary(
                app_key=app_key, instance_index=instance_index, session_id=session_id, source_tier=effective_tier
            )
        )
    except DB_ERRORS:
        LOGGER.warning("Failed to fetch jobs for %s", app_key, exc_info=True)
        response.status_code = 503
        return []

    # Enrich DB rows with live heap state. All enrichment happens on the returned
    # snapshot — never inside the heap lock. INVARIANT: get_all_jobs() acquires
    # FairAsyncRLock internally and returns a list copy.
    try:
        live_jobs = await scheduler_service.get_all_jobs()
    except Exception:
        LOGGER.warning("Failed to fetch live scheduler jobs for enrichment; returning DB rows only", exc_info=True)
        return db_jobs

    # Build lookup by db_id (skip jobs not yet persisted)
    live_by_db_id = {job.db_id: job for job in live_jobs if job.db_id is not None}

    enriched: list[JobSummary] = []
    for js in db_jobs:
        try:
            live_job = live_by_db_id.get(js.job_id)
            if live_job is not None:
                # OR semantics: preserve DB-derived cancelled_at signal even when the live heap
                # shows cancelled=False (transient window between cancellation and heap removal).
                is_cancelled = live_job.cancelled or js.cancelled

                # Don't expose next_run/fire_at for cancelled jobs — they won't fire again.
                if is_cancelled:
                    next_run_ts = None
                    fire_at_ts = None
                else:
                    # next_run and fire_at as epoch floats, matching last_executed_at convention
                    next_run_ts = live_job.next_run.timestamp()
                    fire_at_ts = live_job.fire_at.timestamp() if live_job.jitter is not None else None

                enriched.append(
                    js.model_copy(
                        update={
                            "next_run": next_run_ts,
                            "fire_at": fire_at_ts,
                            "jitter": live_job.jitter,
                            "cancelled": is_cancelled,
                        }
                    )
                )
            else:
                # No live match — leave next_run/fire_at/jitter as None; cancelled from DB
                enriched.append(js)
        except Exception:
            LOGGER.warning("Failed to enrich job summary for job_id=%s; using DB row", js.job_id, exc_info=True)
            enriched.append(js)

    return enriched


@router.get("/handler/{listener_id}/invocations", response_model=list[HandlerInvocation])
async def handler_invocations(
    listener_id: int,
    telemetry: TelemetryDep,
    response: Response,
    limit: int = Query(default=50, ge=1, le=500),  # pyright: ignore[reportCallInDefaultInitializer]
    session_id: int | None = Query(default=None),  # pyright: ignore[reportCallInDefaultInitializer]
) -> list[HandlerInvocation]:
    """Invocation history for a specific handler."""
    try:
        return list(
            await telemetry.get_handler_invocations(listener_id=listener_id, limit=limit, session_id=session_id)
        )
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
    session_id: int | None = Query(default=None),  # pyright: ignore[reportCallInDefaultInitializer]
) -> list[JobExecution]:
    """Execution history for a specific job."""
    try:
        return list(await telemetry.get_job_executions(job_id=job_id, limit=limit, session_id=session_id))
    except DB_ERRORS:
        LOGGER.warning("Failed to fetch executions for job %s", job_id, exc_info=True)
        response.status_code = 503
        return []


@router.get("/dashboard/kpis", response_model=DashboardKpisResponse)
async def dashboard_kpis(
    runtime: RuntimeDep,
    telemetry: TelemetryDep,
    session_id: int | None = Query(default=None),  # pyright: ignore[reportCallInDefaultInitializer]
    source_tier: QuerySourceTier | None = _SOURCE_TIER_PARAM,
) -> DashboardKpisResponse:
    """Global KPI metrics for the dashboard strip."""
    effective_tier = source_tier if source_tier is not None else "app"
    try:
        summary = await telemetry.get_global_summary(session_id=session_id, source_tier=effective_tier)
    except DB_ERRORS:
        LOGGER.warning("Failed to fetch global summary for dashboard KPIs", exc_info=True)
        status = runtime.get_system_status()
        return DashboardKpisResponse(
            total_handlers=0,
            total_jobs=0,
            total_invocations=0,
            total_executions=0,
            total_errors=0,
            total_job_errors=0,
            avg_handler_duration_ms=0.0,
            avg_job_duration_ms=0.0,
            error_rate=0.0,
            error_rate_class=classify_error_rate(0.0),
            uptime_seconds=status.uptime_seconds,
        )

    total = summary.listeners.total_invocations + summary.jobs.total_executions
    errors = summary.listeners.total_errors + summary.jobs.total_errors
    error_rate = (errors / total * 100) if total > 0 else 0.0

    status = runtime.get_system_status()

    return DashboardKpisResponse(
        total_handlers=summary.listeners.total_listeners,
        total_jobs=summary.jobs.total_jobs,
        total_invocations=summary.listeners.total_invocations,
        total_executions=summary.jobs.total_executions,
        total_errors=summary.listeners.total_errors,
        total_job_errors=summary.jobs.total_errors,
        avg_handler_duration_ms=summary.listeners.avg_duration_ms or 0.0,
        avg_job_duration_ms=summary.jobs.avg_duration_ms or 0.0,
        error_rate=error_rate,
        error_rate_class=classify_error_rate(error_rate),
        uptime_seconds=status.uptime_seconds,
    )


@router.get("/dashboard/app-grid", response_model=DashboardAppGridResponse)
async def dashboard_app_grid(
    runtime: RuntimeDep,
    telemetry: TelemetryDep,
    session_id: int | None = Query(default=None),  # pyright: ignore[reportCallInDefaultInitializer]
) -> DashboardAppGridResponse:
    """Per-app health data for the dashboard grid.

    Always uses ``source_tier='app'`` — framework actors are shown via FrameworkHealth,
    not the manifest-driven app grid.
    """
    snapshot = runtime.get_all_manifests_snapshot()
    try:
        summaries = await telemetry.get_all_app_summaries(session_id=session_id, source_tier="app")
    except DB_ERRORS:
        LOGGER.warning("Failed to fetch app summaries for dashboard grid", exc_info=True)
        summaries = {}

    empty = AppHealthSummary(
        handler_count=0,
        job_count=0,
        total_invocations=0,
        total_errors=0,
        total_executions=0,
        total_job_errors=0,
        avg_duration_ms=0.0,
        last_activity_ts=None,
    )

    entries = []
    for manifest in snapshot.manifests:
        health = summaries.get(manifest.app_key, empty)
        rate = _error_rate_from_summary(health)
        entries.append(
            DashboardAppGridEntry(
                app_key=manifest.app_key,
                status=manifest.status,
                display_name=manifest.display_name,
                instance_count=manifest.instance_count,
                handler_count=health.handler_count,
                job_count=health.job_count,
                total_invocations=health.total_invocations,
                total_errors=health.total_errors,
                total_executions=health.total_executions,
                total_job_errors=health.total_job_errors,
                avg_duration_ms=health.avg_duration_ms,
                last_activity_ts=health.last_activity_ts,
                health_status=_health_status_from_summary(health),
                error_rate=rate,
                error_rate_class=classify_error_rate(rate),
            )
        )

    return DashboardAppGridResponse(apps=entries)


@router.get("/dashboard/errors", response_model=DashboardErrorsResponse)
async def dashboard_errors(
    telemetry: TelemetryDep,
    session_id: int | None = Query(default=None),  # pyright: ignore[reportCallInDefaultInitializer]
    source_tier: QuerySourceTier | None = _SOURCE_TIER_PARAM,
) -> DashboardErrorsResponse:
    """Recent errors for the dashboard error feed."""
    effective_tier = source_tier if source_tier is not None else "app"
    since_ts = time.time() - 86400
    try:
        raw_errors = await telemetry.get_recent_errors(
            since_ts=since_ts, limit=10, session_id=session_id, source_tier=effective_tier
        )
    except DB_ERRORS:
        LOGGER.warning("Failed to fetch recent errors for dashboard", exc_info=True)
        return DashboardErrorsResponse(errors=[])

    typed_errors: list[HandlerErrorEntry | JobErrorEntry] = []
    for err in raw_errors:
        if isinstance(err, JobErrorRecord):
            typed_errors.append(
                JobErrorEntry(
                    job_id=err.job_id,
                    job_name=err.job_name,
                    error_message=err.error_message or "",
                    error_type=err.error_type or "",
                    execution_start_ts=err.execution_start_ts,
                    app_key=err.app_key,
                    source_tier=err.source_tier,
                )
            )
        elif isinstance(err, HandlerErrorRecord):
            typed_errors.append(
                HandlerErrorEntry(
                    listener_id=err.listener_id,
                    topic=err.topic,
                    handler_method=err.handler_method,
                    error_message=err.error_message or "",
                    error_type=err.error_type or "",
                    execution_start_ts=err.execution_start_ts,
                    app_key=err.app_key,
                    source_tier=err.source_tier,
                )
            )

    return DashboardErrorsResponse(errors=typed_errors)


@router.get("/dashboard/framework-summary", response_model=FrameworkSummaryResponse)
async def dashboard_framework_summary(
    telemetry: TelemetryDep,
    session_id: int | None = Query(default=None),  # pyright: ignore[reportCallInDefaultInitializer]
) -> FrameworkSummaryResponse:
    """Combined framework KPIs + recent errors in one atomic response.

    Eliminates the dual-fetch desync between error count badge and error feed
    that occurs when two separate calls race under incident conditions.
    """
    total_errors = 0
    total_job_errors = 0
    typed_errors: list[HandlerErrorEntry | JobErrorEntry] = []

    try:
        summary = await telemetry.get_global_summary(session_id=session_id, source_tier="framework")
        total_errors = summary.listeners.total_errors
        total_job_errors = summary.jobs.total_errors
    except DB_ERRORS:
        LOGGER.warning("Failed to fetch framework global summary", exc_info=True)

    since_ts = time.time() - 86400
    try:
        raw_errors = await telemetry.get_recent_errors(
            since_ts=since_ts, limit=10, session_id=session_id, source_tier="framework"
        )
        for err in raw_errors:
            if isinstance(err, JobErrorRecord):
                typed_errors.append(
                    JobErrorEntry(
                        job_id=err.job_id,
                        job_name=err.job_name,
                        error_message=err.error_message or "",
                        error_type=err.error_type or "",
                        execution_start_ts=err.execution_start_ts,
                        app_key=err.app_key,
                        source_tier=err.source_tier,
                    )
                )
            elif isinstance(err, HandlerErrorRecord):
                typed_errors.append(
                    HandlerErrorEntry(
                        listener_id=err.listener_id,
                        topic=err.topic,
                        handler_method=err.handler_method,
                        error_message=err.error_message or "",
                        error_type=err.error_type or "",
                        execution_start_ts=err.execution_start_ts,
                        app_key=err.app_key,
                        source_tier=err.source_tier,
                    )
                )
    except DB_ERRORS:
        LOGGER.warning("Failed to fetch framework recent errors", exc_info=True)

    return FrameworkSummaryResponse(
        total_errors=total_errors,
        total_job_errors=total_job_errors,
        errors=typed_errors,
    )
