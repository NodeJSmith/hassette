"""JSON telemetry endpoints for the Preact SPA.

All endpoints resolve ``session_id`` server-side via ``safe_session_id()`` —
the SPA never needs to know or pass a session ID.
"""

from fastapi import APIRouter, Query

from hassette.core.telemetry_models import AppHealthSummary
from hassette.web.dependencies import RuntimeDep, TelemetryDep
from hassette.web.models import (
    AppHealthResponse,
    DashboardAppGridEntry,
    DashboardAppGridResponse,
    DashboardErrorsResponse,
    DashboardKpisResponse,
    HandlerErrorEntry,
    JobErrorEntry,
    ListenerWithSummary,
)
from hassette.web.telemetry_helpers import (
    classify_error_rate,
    classify_health_bar,
    compute_health_metrics,
    format_handler_summary,
    safe_session_id,
)

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


def _health_status_from_summary(summary: AppHealthSummary) -> str:
    """Derive a health status label from an app health summary."""
    total = summary.total_invocations + summary.total_executions
    errors = summary.total_errors + summary.total_job_errors
    if total == 0:
        return "unknown"
    success_rate = ((total - errors) / total) * 100
    return classify_health_bar(success_rate)


@router.get("/app/{app_key}/health", response_model=AppHealthResponse)
async def app_health(
    app_key: str,
    runtime: RuntimeDep,
    telemetry: TelemetryDep,
    instance_index: int = 0,
) -> AppHealthResponse:
    """Health strip metrics for a single app instance."""
    session_id = safe_session_id(runtime)
    listeners = await telemetry.get_listener_summary(
        app_key=app_key, instance_index=instance_index, session_id=session_id
    )
    jobs = await telemetry.get_job_summary(app_key=app_key, instance_index=instance_index, session_id=session_id)
    metrics = compute_health_metrics(listeners, jobs)

    total_invocations = sum(ls.total_invocations for ls in listeners)
    total_errors = sum(ls.failed for ls in listeners)
    total = total_invocations + sum(j.total_executions for j in jobs)
    errors = total_errors + sum(j.failed for j in jobs)
    success_rate = ((total - errors) / total * 100) if total > 0 else 100.0

    return AppHealthResponse(
        error_rate=metrics["error_rate"],
        error_rate_class=classify_error_rate(metrics["error_rate"]),
        handler_avg_duration=metrics["handler_avg_duration"],
        job_avg_duration=metrics["job_avg_duration"],
        last_activity_ts=metrics["last_activity_ts"],
        health_status=classify_health_bar(success_rate),
    )


@router.get("/app/{app_key}/listeners", response_model=list[ListenerWithSummary])
async def app_listeners(
    app_key: str,
    runtime: RuntimeDep,
    telemetry: TelemetryDep,
    instance_index: int = 0,
) -> list[ListenerWithSummary]:
    """Listener metrics with human-readable handler summaries."""
    session_id = safe_session_id(runtime)
    listeners = await telemetry.get_listener_summary(
        app_key=app_key, instance_index=instance_index, session_id=session_id
    )
    return [
        ListenerWithSummary(
            listener_id=ls.listener_id,
            app_key=ls.app_key,
            instance_index=ls.instance_index,
            topic=ls.topic,
            handler_method=ls.handler_method,
            total_invocations=ls.total_invocations,
            successful=ls.successful,
            failed=ls.failed,
            di_failures=ls.di_failures,
            cancelled=ls.cancelled,
            avg_duration_ms=ls.avg_duration_ms,
            min_duration_ms=ls.min_duration_ms,
            max_duration_ms=ls.max_duration_ms,
            total_duration_ms=ls.total_duration_ms,
            predicate_description=ls.predicate_description,
            human_description=ls.human_description,
            debounce=ls.debounce,
            throttle=ls.throttle,
            once=ls.once,
            priority=ls.priority,
            last_invoked_at=ls.last_invoked_at,
            last_error_message=ls.last_error_message,
            last_error_type=ls.last_error_type,
            handler_summary=format_handler_summary(ls),
        )
        for ls in listeners
    ]


@router.get("/app/{app_key}/jobs")
async def app_jobs(
    app_key: str,
    runtime: RuntimeDep,
    telemetry: TelemetryDep,
    instance_index: int = 0,
) -> list:
    """Job summaries for a single app instance."""
    session_id = safe_session_id(runtime)
    jobs = await telemetry.get_job_summary(app_key=app_key, instance_index=instance_index, session_id=session_id)
    return [j.model_dump() for j in jobs]


@router.get("/handler/{listener_id}/invocations")
async def handler_invocations(
    listener_id: int,
    telemetry: TelemetryDep,
    limit: int = Query(default=50, ge=1, le=500),  # pyright: ignore[reportCallInDefaultInitializer]
) -> list:
    """Invocation history for a specific handler."""
    invocations = await telemetry.get_handler_invocations(listener_id=listener_id, limit=limit)
    return [inv.model_dump() for inv in invocations]


@router.get("/job/{job_id}/executions")
async def job_executions(
    job_id: int,
    telemetry: TelemetryDep,
    limit: int = Query(default=50, ge=1, le=500),  # pyright: ignore[reportCallInDefaultInitializer]
) -> list:
    """Execution history for a specific job."""
    executions = await telemetry.get_job_executions(job_id=job_id, limit=limit)
    return [ex.model_dump() for ex in executions]


@router.get("/dashboard/kpis", response_model=DashboardKpisResponse)
async def dashboard_kpis(
    runtime: RuntimeDep,
    telemetry: TelemetryDep,
) -> DashboardKpisResponse:
    """Global KPI metrics for the dashboard strip."""
    session_id = safe_session_id(runtime)
    summary = await telemetry.get_global_summary(session_id=session_id)
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
        avg_job_duration_ms=0.0,  # JobGlobalStats doesn't have avg_duration_ms
        error_rate=error_rate,
        error_rate_class=classify_error_rate(error_rate),
        uptime_seconds=status.uptime_seconds,
    )


@router.get("/dashboard/app-grid", response_model=DashboardAppGridResponse)
async def dashboard_app_grid(
    runtime: RuntimeDep,
    telemetry: TelemetryDep,
) -> DashboardAppGridResponse:
    """Per-app health data for the dashboard grid."""
    session_id = safe_session_id(runtime)
    snapshot = runtime.get_all_manifests_snapshot()
    try:
        summaries = await telemetry.get_all_app_summaries(session_id=session_id)
    except Exception:
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
        entries.append(
            DashboardAppGridEntry(
                app_key=manifest.app_key,
                status=manifest.status,
                display_name=manifest.display_name,
                handler_count=health.handler_count,
                job_count=health.job_count,
                total_invocations=health.total_invocations,
                total_errors=health.total_errors,
                total_executions=health.total_executions,
                total_job_errors=health.total_job_errors,
                avg_duration_ms=health.avg_duration_ms,
                last_activity_ts=health.last_activity_ts,
                health_status=_health_status_from_summary(health),
            )
        )

    return DashboardAppGridResponse(apps=entries)


@router.get("/dashboard/errors", response_model=DashboardErrorsResponse)
async def dashboard_errors(
    runtime: RuntimeDep,
    telemetry: TelemetryDep,
) -> DashboardErrorsResponse:
    """Recent errors for the dashboard error feed."""
    session_id = safe_session_id(runtime)
    raw_errors = await telemetry.get_recent_errors(since_ts=0, limit=10, session_id=session_id)

    typed_errors: list[HandlerErrorEntry | JobErrorEntry] = []
    for err in raw_errors:
        kind = err.get("kind", "handler")
        if kind == "job":
            typed_errors.append(
                JobErrorEntry(
                    job_id=err.get("job_id", 0),
                    job_name=err.get("job_name", ""),
                    error_message=err.get("error_message", ""),
                    error_type=err.get("error_type", ""),
                    timestamp=err.get("timestamp", 0.0),
                    app_key=err.get("app_key", ""),
                )
            )
        else:
            typed_errors.append(
                HandlerErrorEntry(
                    listener_id=err.get("listener_id", 0),
                    topic=err.get("topic", ""),
                    handler_method=err.get("handler_method", ""),
                    error_message=err.get("error_message", ""),
                    error_type=err.get("error_type", ""),
                    timestamp=err.get("timestamp", 0.0),
                    app_key=err.get("app_key", ""),
                )
            )

    return DashboardErrorsResponse(errors=typed_errors)
