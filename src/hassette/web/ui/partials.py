"""HTMX partial fragment routes for the Hassette Web UI."""

from fastapi import APIRouter, Query, Request
from starlette.responses import HTMLResponse, Response

from hassette.web.dependencies import RuntimeDep, TelemetryDep
from hassette.web.ui import templates
from hassette.web.ui.context import (
    alert_context,
    compute_app_grid_health,
    compute_health_metrics,
    format_handler_summary,
    safe_session_id,
)

router = APIRouter()


@router.get("/partials/log-entries", response_class=HTMLResponse)
async def log_entries_partial(
    request: Request,
    runtime: RuntimeDep,
    level: str | None = None,
    app_key: str | None = None,
    limit: int = Query(default=100, ge=1, le=2000),  # pyright: ignore[reportCallInDefaultInitializer]
) -> HTMLResponse:
    logs = runtime.get_recent_logs(limit=limit, app_key=app_key, level=level)
    show_app_column = not app_key
    return templates.TemplateResponse(
        request, "partials/log_entries.html", {"logs": logs, "show_app_column": show_app_column}
    )


@router.get("/partials/manifest-list", response_class=HTMLResponse)
async def manifest_list_partial(
    request: Request,
    runtime: RuntimeDep,
    status: str | None = None,
) -> HTMLResponse:
    snapshot = runtime.get_all_manifests_snapshot()
    manifests = snapshot.manifests
    if status:
        manifests = [m for m in manifests if m.status == status]
    return templates.TemplateResponse(request, "partials/manifest_list.html", {"manifests": manifests})


@router.get("/partials/dashboard-app-grid", response_class=HTMLResponse)
async def dashboard_app_grid_partial(request: Request, runtime: RuntimeDep, telemetry: TelemetryDep) -> HTMLResponse:
    snapshot = runtime.get_all_manifests_snapshot()
    app_health = await compute_app_grid_health(snapshot.manifests, telemetry)
    return templates.TemplateResponse(
        request,
        "partials/dashboard_app_grid.html",
        {"manifests": snapshot.manifests, "app_health": app_health},
    )


@router.get("/partials/dashboard-errors", response_class=HTMLResponse)
async def dashboard_errors_partial(request: Request, runtime: RuntimeDep, telemetry: TelemetryDep) -> HTMLResponse:
    session_id = safe_session_id(runtime)
    recent_errors = await telemetry.get_recent_errors(since_ts=0, limit=10, session_id=session_id)
    return templates.TemplateResponse(request, "partials/dashboard_errors.html", {"recent_errors": recent_errors})


@router.get("/partials/alert-failed-apps", response_class=HTMLResponse)
async def alert_failed_apps_partial(request: Request, runtime: RuntimeDep) -> HTMLResponse:
    ctx = alert_context(runtime)
    return templates.TemplateResponse(request, "partials/alert_failed_apps.html", ctx)


@router.get("/partials/app-detail-listeners/{app_key}", response_class=HTMLResponse)
async def app_detail_listeners_partial(
    app_key: str, request: Request, telemetry: TelemetryDep, instance_index: int = 0
) -> HTMLResponse:
    listeners = await telemetry.get_listener_summary(app_key=app_key, instance_index=instance_index)
    return templates.TemplateResponse(
        request,
        "partials/app_detail_listeners.html",
        {"listeners": listeners},
    )


@router.get("/partials/app-detail-jobs/{app_key}", response_class=HTMLResponse)
async def app_detail_jobs_partial(
    app_key: str, request: Request, telemetry: TelemetryDep, instance_index: int = 0
) -> HTMLResponse:
    jobs = await telemetry.get_job_summary(app_key=app_key, instance_index=instance_index)
    return templates.TemplateResponse(
        request,
        "partials/app_detail_jobs.html",
        {"jobs": jobs},
    )


@router.get("/partials/instance-listeners/{app_key}/{index}", response_class=HTMLResponse)
async def instance_listeners_partial(
    app_key: str, index: int, request: Request, telemetry: TelemetryDep
) -> HTMLResponse:
    listeners = await telemetry.get_listener_summary(app_key=app_key, instance_index=index)
    return templates.TemplateResponse(request, "partials/app_detail_listeners.html", {"listeners": listeners})


@router.get("/partials/instance-jobs/{app_key}/{index}", response_class=HTMLResponse)
async def instance_jobs_partial(app_key: str, index: int, request: Request, telemetry: TelemetryDep) -> HTMLResponse:
    jobs = await telemetry.get_job_summary(app_key=app_key, instance_index=index)
    return templates.TemplateResponse(request, "partials/app_detail_jobs.html", {"jobs": jobs})


# ──────────────────────────────────────────────────────────────────────
# App Detail partials (handler invocations, job executions, health, etc.)
# ──────────────────────────────────────────────────────────────────────


@router.get("/partials/handler-invocations/{app_key}/{listener_id}", response_class=HTMLResponse)
async def handler_invocations_partial(
    app_key: str,  # noqa: ARG001 — path segment for URL consistency
    listener_id: int,
    request: Request,
    telemetry: TelemetryDep,
    limit: int = 50,
) -> HTMLResponse:
    invocations = await telemetry.get_handler_invocations(listener_id=listener_id, limit=limit)
    return templates.TemplateResponse(
        request,
        "partials/handler_invocations.html",
        {"invocations": invocations, "listener_id": listener_id},
    )


@router.get("/partials/job-executions/{app_key}/{job_id}", response_class=HTMLResponse)
async def job_executions_partial(
    app_key: str,
    job_id: int,
    request: Request,
    telemetry: TelemetryDep,
    limit: int = 50,
) -> HTMLResponse:
    executions = await telemetry.get_job_executions(job_id=job_id, limit=limit)
    return templates.TemplateResponse(
        request,
        "partials/job_executions.html",
        {"executions": executions, "job_id": job_id, "app_key": app_key},
    )


@router.get("/partials/app-handler-stats/{app_key}", response_class=HTMLResponse)
async def app_handler_stats_partial(
    app_key: str, request: Request, telemetry: TelemetryDep, instance_index: int = 0
) -> HTMLResponse:
    """Stats-only partial for 5s polling. Returns just invocation counts and last-fired."""
    listeners = await telemetry.get_listener_summary(app_key=app_key, instance_index=instance_index)
    return templates.TemplateResponse(
        request,
        "partials/app_handler_stats.html",
        {"listeners": listeners},
    )


@router.get("/partials/app-health-strip/{app_key}", response_class=HTMLResponse)
async def app_health_strip_partial(
    app_key: str, request: Request, runtime: RuntimeDep, telemetry: TelemetryDep, instance_index: int = 0
) -> HTMLResponse:
    manifest_snapshot = runtime.get_all_manifests_snapshot()
    manifest = next((m for m in manifest_snapshot.manifests if m.app_key == app_key), None)
    instance = None
    if manifest:
        instance = next((i for i in manifest.instances if i.index == instance_index), None)

    listeners = await telemetry.get_listener_summary(app_key=app_key, instance_index=instance_index)
    jobs = await telemetry.get_job_summary(app_key=app_key, instance_index=instance_index)
    health = compute_health_metrics(listeners, jobs)

    ctx = {
        "init_status": str(instance.status) if instance else (manifest.status if manifest else "unknown"),
        **health,
    }
    return templates.TemplateResponse(request, "partials/app_health_strip.html", ctx)


@router.get("/partials/app-handlers/{app_key}", response_class=HTMLResponse)
async def app_handlers_partial(
    app_key: str, request: Request, telemetry: TelemetryDep, instance_index: int = 0
) -> HTMLResponse:
    listeners = await telemetry.get_listener_summary(app_key=app_key, instance_index=instance_index)
    handler_summaries = {ls.listener_id: format_handler_summary(ls) for ls in listeners}
    return templates.TemplateResponse(
        request,
        "partials/app_handlers.html",
        {"listeners": listeners, "handler_summaries": handler_summaries, "app_key": app_key},
    )


@router.get("/partials/app-handlers/{app_key}/{index}", response_class=HTMLResponse)
async def app_handlers_instance_partial(
    app_key: str, index: int, request: Request, telemetry: TelemetryDep
) -> HTMLResponse:
    listeners = await telemetry.get_listener_summary(app_key=app_key, instance_index=index)
    handler_summaries = {ls.listener_id: format_handler_summary(ls) for ls in listeners}
    return templates.TemplateResponse(
        request,
        "partials/app_handlers.html",
        {"listeners": listeners, "handler_summaries": handler_summaries, "app_key": app_key},
    )


@router.get("/partials/app-jobs/{app_key}", response_class=HTMLResponse)
async def app_jobs_partial(
    app_key: str, request: Request, telemetry: TelemetryDep, instance_index: int = 0
) -> HTMLResponse:
    jobs = await telemetry.get_job_summary(app_key=app_key, instance_index=instance_index)
    return templates.TemplateResponse(
        request,
        "partials/app_jobs.html",
        {"jobs": jobs, "app_key": app_key},
    )


@router.get("/partials/app-jobs/{app_key}/{index}", response_class=HTMLResponse)
async def app_jobs_instance_partial(
    app_key: str, index: int, request: Request, telemetry: TelemetryDep
) -> HTMLResponse:
    jobs = await telemetry.get_job_summary(app_key=app_key, instance_index=index)
    return templates.TemplateResponse(
        request,
        "partials/app_jobs.html",
        {"jobs": jobs, "app_key": app_key},
    )


@router.get("/partials/app-logs/{app_key}", response_class=HTMLResponse)
async def app_logs_partial(app_key: str, request: Request, runtime: RuntimeDep, limit: int = 50) -> HTMLResponse:
    logs = runtime.get_recent_logs(app_key=app_key, limit=limit)
    return templates.TemplateResponse(
        request,
        "partials/app_logs.html",
        {"logs": logs, "app_key": app_key},
    )


@router.get("/partials/app-logs/{app_key}/{index}", response_class=HTMLResponse)
async def app_logs_instance_partial(
    app_key: str,
    index: int,  # noqa: ARG001 — instance index for URL consistency; logs are app-scoped
    request: Request,
    runtime: RuntimeDep,
    limit: int = 50,
) -> HTMLResponse:
    logs = runtime.get_recent_logs(app_key=app_key, limit=limit)
    return templates.TemplateResponse(
        request,
        "partials/app_logs.html",
        {"logs": logs, "app_key": app_key},
    )


# ──────────────────────────────────────────────────────────────────────
# Deferred feature placeholders (return 501 Not Implemented)
# ──────────────────────────────────────────────────────────────────────


@router.post("/partials/log-level/{app_key}")
async def set_log_level_placeholder(app_key: str) -> Response:  # noqa: ARG001
    """Placeholder for log level toggle. Returns 501 until implemented."""
    return Response(content="Log level toggle not yet implemented", status_code=501)


@router.post("/partials/app-enable/{app_key}")
async def toggle_app_enable_placeholder(app_key: str) -> Response:  # noqa: ARG001
    """Placeholder for enable/disable toggle. Returns 501 until implemented."""
    return Response(content="Enable/disable toggle not yet implemented", status_code=501)


@router.post("/partials/run-job/{app_key}/{job_id}")
async def run_job_placeholder(app_key: str, job_id: int) -> Response:  # noqa: ARG001
    """Placeholder for run-now button. Returns 501 until implemented."""
    return Response(content="Run-now not yet implemented", status_code=501)
