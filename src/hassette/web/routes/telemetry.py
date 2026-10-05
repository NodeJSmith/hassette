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
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response
from hassette_wire import (
    ActivityBucket,
    ActivityFeedEntry,
    AppActivity,
    AppActivityStats,
    AppGridEntry,
    AppGridResponse,
    AppHealth,
    BlockingFindingsResponse,
    Execution,
    JobSummary,
    LastError,
    LastErrorResult,
    ListenerWithSummary,
    ProblemCode,
    TelemetryStatusResponse,
    UnattributedBlockingResponse,
)

from hassette.exceptions import TelemetryUnavailableError
from hassette.schemas.execution_models import AppLastError
from hassette.schemas.query_constants import DEFAULT_QUERY_LIMIT, DEFAULT_SPARKLINE_BUCKETS
from hassette.schemas.summary_models import AppHealthAggregates, AppHealthSummary
from hassette.web.dependencies import (
    AppKeyPath,
    HassetteDep,
    LimitQuery,
    OptionalInstanceIndexQuery,
    RuntimeDep,
    SchedulerDep,
    SinceQuery,
    SourceTierQuery,
    TelemetryDep,
    TelemetryFiltersDep,
)
from hassette.web.errors import problem_responses
from hassette.web.mappers import app_summary_from, to_listener_with_summary
from hassette.web.telemetry_helpers import build_app_health
from hassette.web.utils import enrich_jobs_with_live_data

LOGGER = getLogger(__name__)

NO_TELEMETRY_SUMMARY = AppHealthSummary(handler_count=0, job_count=0, aggregates=AppHealthAggregates.empty())
"""The summary of an app with no telemetry rows in the window: zero counts, no averages."""

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


@router.get(
    "/app/{app_key}/health",
    response_model=AppHealth,
    responses=problem_responses(ProblemCode.TELEMETRY_UNAVAILABLE),
)
async def app_health(
    app_key: AppKeyPath,
    telemetry: TelemetryDep,
    filters: TelemetryFiltersDep,
) -> AppHealth:
    """Health strip metrics for a single app instance."""
    agg = await telemetry.get_app_health_aggregates(app_key=app_key, **filters.query_kwargs)
    return build_app_health(agg)


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

    ``schedule_status``/``schedule_status_reason``, ``jitter``, and, for ``SCHEDULED`` jobs, live timing
    (``next_run``, ``fire_at``) are joined from the live scheduler registry by
    ``db_id``. If the live registry can't be read, the DB rows are returned without enrichment
    and a warning is logged. If the telemetry DB can't be read, the route answers
    ``telemetry_unavailable``.
    """
    db_jobs = list(await telemetry.get_job_summary(app_key=app_key, **filters.query_kwargs))
    return await enrich_jobs_with_live_data(db_jobs, scheduler_service)


@router.get(
    "/app/{app_key}/blocking",
    response_model=BlockingFindingsResponse,
    responses=problem_responses(ProblemCode.TELEMETRY_UNAVAILABLE),
)
async def app_blocking_findings(
    app_key: AppKeyPath,
    telemetry: TelemetryDep,
    instance_index: OptionalInstanceIndexQuery = None,
    since: SinceQuery = None,
) -> BlockingFindingsResponse:
    """Blocking-IO findings for one app: attributed events grouped by app call site.

    Without ``instance_index``, findings cover every instance, which is what the multi-instance
    parent overview shows; with it, only that instance's events are counted.
    """
    return await telemetry.get_blocking_findings(app_key=app_key, instance_index=instance_index, since=since)


@router.get(
    "/blocking/findings",
    response_model=BlockingFindingsResponse,
    responses=problem_responses(ProblemCode.TELEMETRY_UNAVAILABLE),
)
async def all_blocking_findings(telemetry: TelemetryDep, since: SinceQuery = None) -> BlockingFindingsResponse:
    """Blocking-IO findings for every app and instance, in one response."""
    return await telemetry.get_blocking_findings(app_key=None, instance_index=None, since=since)


@router.get(
    "/blocking/unattributed",
    response_model=UnattributedBlockingResponse,
    responses=problem_responses(ProblemCode.TELEMETRY_UNAVAILABLE),
)
async def unattributed_blocking(telemetry: TelemetryDep, since: SinceQuery = None) -> UnattributedBlockingResponse:
    """Loop stalls credited to no app (displaced or framework), for the diagnostics page."""
    return await telemetry.get_unattributed_blocking(since=since)


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
    "/app-grid",
    response_model=AppGridResponse,
    responses=problem_responses(ProblemCode.TELEMETRY_UNAVAILABLE),
)
async def app_grid(
    runtime: RuntimeDep,
    telemetry: TelemetryDep,
    since: SinceQuery = None,
) -> AppGridResponse:
    """Every app joined with its activity over ``since``, for the Apps grid.

    The app spine is queried from the ``app_manifests`` DB table (``telemetry_unavailable`` on
    failure) and overlaid with live runtime state via
    ``RuntimeQueryService.overlay_manifest_rows()``. Each telemetry enrichment below is one
    all-apps query that fills one ``AppActivity`` part. A failed query leaves its part ``None`` in
    every row and the response continues at 200, with one summary warning naming the failed parts
    — see ``.claude/rules/web-api.md``. ``activity_buckets`` and ``last_error`` only run for a
    window, so they are ``None`` when ``since`` is ``None``.

    Always uses ``source_tier='app'`` — framework actors are shown via FrameworkHealth,
    not the manifest-driven app grid.
    """
    db_rows = await telemetry.get_all_app_manifests()
    manifest_infos = runtime.overlay_manifest_rows(db_rows)
    failed: list[str] = []

    summaries: dict[str, AppHealthSummary] | None = None
    try:
        summaries = await telemetry.get_all_app_summaries(since=since, source_tier="app")
    except TelemetryUnavailableError:
        LOGGER.warning("Failed to fetch app summaries for the app grid", exc_info=True)
        failed.append("stats")

    per_app_buckets: dict[str, list[tuple[int, int]]] | None = None
    per_app_errors: dict[str, AppLastError] | None = None
    if since is not None:
        try:
            per_app_buckets = await telemetry.get_per_app_activity_buckets(
                since,
                time.time(),
                num_buckets=DEFAULT_SPARKLINE_BUCKETS,
                source_tier="app",
            )
        except TelemetryUnavailableError:
            LOGGER.warning("Failed to fetch per-app activity buckets", exc_info=True)
            failed.append("activity_buckets")
        try:
            per_app_errors = await telemetry.get_per_app_last_errors(since=since, source_tier="app")
        except TelemetryUnavailableError:
            LOGGER.warning("Failed to fetch per-app last errors", exc_info=True)
            failed.append("last_error")

    blocking_counts: dict[str, int] | None = None
    try:
        blocking_counts = await telemetry.get_blocking_event_counts(since=since)
    except TelemetryUnavailableError:
        LOGGER.warning("Failed to fetch per-app blocking-event counts", exc_info=True)
        failed.append("blocking_event_count")

    entries = [
        AppGridEntry(
            app=app_summary_from(manifest),
            activity=activity_for(manifest.app_key, summaries, per_app_buckets, per_app_errors, blocking_counts),
        )
        for manifest in manifest_infos
    ]

    if failed:
        LOGGER.warning(
            "App grid served without these activity parts: %s", ", ".join(failed), extra={"failed_parts": failed}
        )
    return AppGridResponse(apps=entries, since=since)


def activity_for(
    app_key: str,
    summaries: dict[str, AppHealthSummary] | None,
    per_app_buckets: dict[str, list[tuple[int, int]]] | None,
    per_app_errors: dict[str, AppLastError] | None,
    blocking_counts: dict[str, int] | None,
) -> AppActivity:
    """Build one app's ``activity`` from the four all-apps enrichment results.

    A ``None`` result (the query failed or didn't run) makes that part ``None``. A result that ran
    but has no entry for this app is real data: the app had nothing in the window, so the part is
    its computed empty value.
    """
    buckets = None if per_app_buckets is None else per_app_buckets.get(app_key, [])
    return AppActivity(
        stats=None if summaries is None else stats_part(summaries.get(app_key, NO_TELEMETRY_SUMMARY)),
        activity_buckets=None if buckets is None else [ActivityBucket(ok=ok, err=err) for ok, err in buckets],
        last_error=None if per_app_errors is None else last_error_part(per_app_errors.get(app_key)),
        blocking_event_count=None if blocking_counts is None else blocking_counts.get(app_key, 0),
    )


def stats_part(summary: AppHealthSummary) -> AppActivityStats:
    """Build an app's ``stats`` part from its health summary."""
    agg = summary.aggregates
    return AppActivityStats(
        handler_count=summary.handler_count,
        job_count=summary.job_count,
        total_invocations=agg.total_invocations,
        total_errors=agg.handler_errors,
        total_timed_out=agg.handler_timed_out,
        total_executions=agg.total_executions,
        total_job_errors=agg.job_errors,
        total_job_timed_out=agg.job_timed_out,
        health=build_app_health(agg),
    )


def last_error_part(err: AppLastError | None) -> LastErrorResult:
    """Build an app's ``last_error`` part from a lookup that ran; ``err`` is ``None`` when it found none."""
    if err is None:
        return LastErrorResult(error=None)
    return LastErrorResult(
        error=LastError(error_message=err.error_message, error_type=err.error_type, ts=err.timestamp)
    )
