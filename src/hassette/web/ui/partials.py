"""HTMX partial fragment routes for the Hassette Web UI."""

from fastapi import APIRouter, Query, Request
from starlette.responses import HTMLResponse

from hassette.web.dependencies import RuntimeDep, SchedulerDep, TelemetryDep
from hassette.web.ui import templates
from hassette.web.ui.context import alert_context, job_to_dict

router = APIRouter()


@router.get("/partials/app-list", response_class=HTMLResponse)
async def app_list_partial(request: Request, runtime: RuntimeDep) -> HTMLResponse:
    app_status = runtime.get_app_status_snapshot()
    return templates.TemplateResponse(request, "partials/app_list.html", {"app_status": app_status})


@router.get("/partials/app-row/{app_key}", response_class=HTMLResponse)
async def app_row_partial(app_key: str, request: Request, runtime: RuntimeDep) -> HTMLResponse:
    app_status = runtime.get_app_status_snapshot()
    app = next((a for a in app_status.apps if a.app_key == app_key), None)
    return templates.TemplateResponse(request, "partials/app_row.html", {"app": app})


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


@router.get("/partials/scheduler-jobs", response_class=HTMLResponse)
async def scheduler_jobs_partial(
    request: Request,
    scheduler: SchedulerDep,
    app_key: str | None = None,
    instance_index: int = 0,
) -> HTMLResponse:
    all_scheduler_jobs = await scheduler.get_all_jobs()
    if app_key is not None:
        jobs = [
            job_to_dict(j, app_key=app_key, instance_index=instance_index)
            for j in all_scheduler_jobs
            if j.owner == app_key
        ]
    else:
        jobs = [job_to_dict(j) for j in all_scheduler_jobs]
    return templates.TemplateResponse(
        request,
        "partials/scheduler_jobs.html",
        {"jobs": jobs},
    )


@router.get("/partials/scheduler-history", response_class=HTMLResponse)
async def scheduler_history_partial(
    request: Request,
    app_key: str | None = None,  # noqa: ARG001 — stub until get_job_executions is wired
    instance_index: int = 0,  # noqa: ARG001 — stub until get_job_executions is wired
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "partials/scheduler_history.html",
        {"history": []},
    )


@router.get("/partials/bus-listeners", response_class=HTMLResponse)
async def bus_listeners_partial(
    request: Request,
    telemetry: TelemetryDep,
    app_key: str | None = None,
    instance_index: int = 0,
) -> HTMLResponse:
    if app_key is not None:
        listeners = await telemetry.get_listener_summary(app_key=app_key, instance_index=instance_index)
    else:
        listeners = []
    return templates.TemplateResponse(
        request,
        "partials/bus_listeners.html",
        {"listeners": listeners},
    )


@router.get("/partials/dashboard-app-grid", response_class=HTMLResponse)
async def dashboard_app_grid_partial(request: Request, runtime: RuntimeDep) -> HTMLResponse:
    snapshot = runtime.get_all_manifests_snapshot()
    return templates.TemplateResponse(request, "partials/dashboard_app_grid.html", {"manifests": snapshot.manifests})


@router.get("/partials/dashboard-timeline", response_class=HTMLResponse)
async def dashboard_timeline_partial(request: Request, runtime: RuntimeDep) -> HTMLResponse:
    events = runtime.get_recent_events(limit=20)
    return templates.TemplateResponse(request, "partials/dashboard_timeline.html", {"events": events})


@router.get("/partials/dashboard-logs", response_class=HTMLResponse)
async def dashboard_logs_partial(request: Request, runtime: RuntimeDep) -> HTMLResponse:
    logs = runtime.get_recent_logs(limit=30)
    return templates.TemplateResponse(request, "partials/dashboard_logs.html", {"logs": logs})


@router.get("/partials/alert-failed-apps", response_class=HTMLResponse)
async def alert_failed_apps_partial(request: Request, runtime: RuntimeDep) -> HTMLResponse:
    ctx = alert_context(runtime)
    return templates.TemplateResponse(request, "partials/alert_failed_apps.html", ctx)


@router.get("/partials/app-detail-listeners/{app_key}", response_class=HTMLResponse)
async def app_detail_listeners_partial(app_key: str, request: Request, telemetry: TelemetryDep) -> HTMLResponse:
    listeners = await telemetry.get_listener_summary(app_key=app_key, instance_index=0)
    return templates.TemplateResponse(
        request,
        "partials/app_detail_listeners.html",
        {"listeners": listeners},
    )


@router.get("/partials/app-detail-jobs/{app_key}", response_class=HTMLResponse)
async def app_detail_jobs_partial(app_key: str, request: Request, scheduler: SchedulerDep) -> HTMLResponse:
    all_scheduler_jobs = await scheduler.get_all_jobs()
    jobs = [job_to_dict(j, app_key=app_key, instance_index=0) for j in all_scheduler_jobs if j.owner == app_key]
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
async def instance_jobs_partial(app_key: str, index: int, request: Request, scheduler: SchedulerDep) -> HTMLResponse:
    all_scheduler_jobs = await scheduler.get_all_jobs()
    jobs = [job_to_dict(j, app_key=app_key, instance_index=index) for j in all_scheduler_jobs if j.owner == app_key]
    return templates.TemplateResponse(request, "partials/app_detail_jobs.html", {"jobs": jobs})
