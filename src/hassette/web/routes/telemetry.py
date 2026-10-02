"""JSON telemetry endpoints for the Preact SPA.

Time-window filtering is client-driven: endpoints accept an optional ``since``
query parameter (Unix epoch float).  Pass a ``since`` value to restrict results
to records with ``execution_start_ts >= since``, or omit it for all-time aggregates.

Required telemetry queries are deliberately not wrapped in ``try``: a ``TelemetryUnavailableError``
propagates to ``telemetry_unavailable_handler`` in ``hassette.web.errors``, which answers the
``telemetry_unavailable`` problem each route declares. Only queries a route can answer without
(enrichment, and the ``/status`` probe) catch it inline.
"""

import time
from logging import getLogger
from typing import TYPE_CHECKING, Annotated, Literal

from fastapi import APIRouter, Query, Response
from hassette_wire import (
    ActivityBucket,
    ActivityFeedEntry,
    AppHealthResponse,
    DashboardAppGridEntry,
    DashboardAppGridResponse,
    Execution,
    HealthStatus,
    JobSummary,
    ListenerWithSummary,
    ProblemCode,
    TelemetryStatusResponse,
)

from hassette.exceptions import TelemetryUnavailableError
from hassette.schemas.query_constants import DEFAULT_QUERY_LIMIT, DEFAULT_SPARKLINE_BUCKETS
from hassette.schemas.summary_models import AppHealthSummary
from hassette.web.dependencies import (
    AppKeyPath,
    HassetteDep,
    LimitQuery,
    RuntimeDep,
    SchedulerDep,
    SinceQuery,
    SourceTierQuery,
    TelemetryDep,
    TelemetryFiltersDep,
)
from hassette.web.errors import problem_responses
from hassette.web.mappers import manifest_response_fields, to_listener_with_summary
from hassette.web.telemetry_helpers import (
    classify_error_rate,
    classify_health_bar,
    compute_error_rate,
    compute_success_rate,
)
from hassette.web.utils import enrich_jobs_with_live_data

if TYPE_CHECKING:
    from hassette.schemas.execution_models import AppLastError

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

    A probe, so a failure answers with this status body rather than a problem body: the CLI
    and container health checks read it as data.
    """
    try:
        await telemetry.check_health()
    except TelemetryUnavailableError:
        LOGGER.warning("Telemetry health check failed", exc_info=True)
        response.status_code = 503
        return TelemetryStatusResponse(degraded=True)

    try:
        overflow, exhausted, shutdown = hassette.get_drop_counters()
    except (AttributeError, RuntimeError):
        overflow, exhausted, shutdown = 0, 0, 0
    try:
        filtered = hassette.command_executor.get_filtered_count()
    except (AttributeError, RuntimeError):
        filtered = 0
    try:
        error_handler_failures = hassette.get_error_handler_failures()
    except (AttributeError, RuntimeError):
        error_handler_failures = 0
    return TelemetryStatusResponse(
        degraded=False,
        dropped_overflow=overflow,
        dropped_exhausted=exhausted,
        dropped_shutdown=shutdown,
        dropped_filtered=filtered,
        error_handler_failures=error_handler_failures,
    )


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


@router.get(
    "/app/{app_key}/health",
    response_model=AppHealthResponse,
    responses=problem_responses(ProblemCode.TELEMETRY_UNAVAILABLE),
)
async def app_health(
    app_key: AppKeyPath,
    telemetry: TelemetryDep,
    filters: TelemetryFiltersDep,
) -> AppHealthResponse:
    """Health strip metrics for a single app instance."""
    agg = await telemetry.get_app_health_aggregates(app_key=app_key, **filters.query_kwargs)
    error_rate = compute_error_rate(
        total_invocations=agg.total_invocations,
        total_executions=agg.total_executions,
        handler_errors=agg.handler_errors + agg.handler_timed_out,
        job_errors=agg.job_errors + agg.job_timed_out,
    )
    return AppHealthResponse(
        error_rate=error_rate,
        error_rate_class=classify_error_rate(error_rate),
        handler_avg_duration=agg.handler_avg_duration_ms,
        job_avg_duration=agg.job_avg_duration_ms,
        last_activity_ts=agg.last_activity_ts,
        health_status=classify_health_bar(compute_success_rate(error_rate)),
    )


@router.get(
    "/app/{app_key}/listeners",
    response_model=list[ListenerWithSummary],
    responses=problem_responses(ProblemCode.TELEMETRY_UNAVAILABLE),
)
async def app_listeners(
    app_key: AppKeyPath,
    telemetry: TelemetryDep,
    hassette: HassetteDep,
    filters: TelemetryFiltersDep,
) -> list[ListenerWithSummary]:
    """Listener metrics with human-readable handler summaries."""
    listeners = await telemetry.get_listener_summary(app_key=app_key, **filters.query_kwargs)
    live_counts = hassette.bus_service.live_execution_counts()
    return [to_listener_with_summary(ls, live_counts) for ls in listeners]


@router.get(
    "/app/{app_key}/activity",
    response_model=list[ActivityFeedEntry],
    responses=problem_responses(ProblemCode.TELEMETRY_UNAVAILABLE),
)
async def app_activity(
    app_key: AppKeyPath,
    telemetry: TelemetryDep,
    instance_index: Annotated[
        int | None, Query(description="App instance index. None returns activity across all instances.")
    ] = None,
    limit: LimitQuery = DEFAULT_QUERY_LIMIT,
    since: SinceQuery = None,
    source_tier: SourceTierQuery = "app",
) -> list[ActivityFeedEntry]:
    """Recent handler invocations and job executions for a single app, merged and sorted by time."""
    return await telemetry.get_app_recent_activity(
        app_key=app_key,
        instance_index=instance_index,
        limit=limit,
        since=since,
        source_tier=source_tier,
    )


@router.get(
    "/app/{app_key}/jobs",
    response_model=list[JobSummary],
    responses=problem_responses(ProblemCode.TELEMETRY_UNAVAILABLE),
)
async def app_jobs(
    app_key: AppKeyPath,
    telemetry: TelemetryDep,
    scheduler_service: SchedulerDep,
    filters: TelemetryFiltersDep,
) -> list[JobSummary]:
    """Job summaries for a single app instance, enriched with live registry data.

    ``schedule_status``/``schedule_status_reason`` and, for ``SCHEDULED`` jobs, live timing
    (``next_run``, ``fire_at``, ``jitter``) are joined from the live scheduler registry by
    ``db_id``. On registry failure the DB rows are returned without enrichment (degraded but
    functional; logged warning, no 500).
    """
    db_jobs = list(await telemetry.get_job_summary(app_key=app_key, **filters.query_kwargs))
    return await enrich_jobs_with_live_data(db_jobs, scheduler_service)


@router.get(
    "/executions", response_model=list[Execution], responses=problem_responses(ProblemCode.TELEMETRY_UNAVAILABLE)
)
async def list_executions(
    telemetry: TelemetryDep,
    kind: Annotated[Literal["handler", "job"] | None, Query(description="Filter by kind: 'handler' or 'job'.")] = None,
    limit: LimitQuery = DEFAULT_QUERY_LIMIT,
    since: SinceQuery = None,
) -> list[Execution]:
    """Combined execution list (handler invocations and job executions).

    Filter by ``kind=handler`` or ``kind=job`` to restrict to one type.
    Each record includes a ``kind`` field that discriminates the execution type.
    """
    return await telemetry.get_executions(kind=kind, limit=limit, since=since)


@router.get(
    "/listener/{listener_id}/executions",
    response_model=list[Execution],
    responses=problem_responses(ProblemCode.TELEMETRY_UNAVAILABLE),
)
async def listener_executions(
    listener_id: int,
    telemetry: TelemetryDep,
    limit: LimitQuery = DEFAULT_QUERY_LIMIT,
    since: SinceQuery = None,
) -> list[Execution]:
    """Execution history for a specific listener (handler invocations)."""
    return await telemetry.get_executions(listener_id=listener_id, limit=limit, since=since)


@router.get(
    "/job/{job_id}/executions",
    response_model=list[Execution],
    responses=problem_responses(ProblemCode.TELEMETRY_UNAVAILABLE),
)
async def job_executions(
    job_id: int,
    telemetry: TelemetryDep,
    limit: LimitQuery = DEFAULT_QUERY_LIMIT,
    since: SinceQuery = None,
) -> list[Execution]:
    """Execution history for a specific job."""
    return await telemetry.get_executions(job_id=job_id, limit=limit, since=since)


@router.get(
    "/execution/{execution_id}",
    response_model=Execution | None,
    responses=problem_responses(ProblemCode.TELEMETRY_UNAVAILABLE),
)
async def get_execution(
    execution_id: str,
    telemetry: TelemetryDep,
) -> Execution | None:
    """Return a single execution record by its UUID."""
    return await telemetry.get_execution_by_id(execution_id)


@router.get(
    "/dashboard/app-grid",
    response_model=DashboardAppGridResponse,
    responses=problem_responses(ProblemCode.TELEMETRY_UNAVAILABLE),
)
async def dashboard_app_grid(
    runtime: RuntimeDep,
    telemetry: TelemetryDep,
    since: SinceQuery = None,
) -> DashboardAppGridResponse:
    """Per-app health data for the dashboard grid.

    The app spine is queried from the ``app_manifests`` DB table (``telemetry_unavailable`` on
    failure) and overlaid with live runtime state via
    ``RuntimeQueryService.overlay_manifest_rows()``. The telemetry enrichment queries below are
    caught individually and degrade to empty defaults while the response continues at 200 —
    see ``.claude/rules/web-api.md``.

    Always uses ``source_tier='app'`` — framework actors are shown via FrameworkHealth,
    not the manifest-driven app grid.
    """
    db_rows = await telemetry.get_all_app_manifests()
    manifest_infos = runtime.overlay_manifest_rows(db_rows)

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
    for manifest in manifest_infos:
        health = summaries.get(manifest.app_key, empty)
        rate = error_rate_from_summary(health)
        buckets = per_app_buckets.get(manifest.app_key, [])
        err_info = per_app_errors.get(manifest.app_key)
        entries.append(
            DashboardAppGridEntry(
                **manifest_response_fields(manifest),
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
