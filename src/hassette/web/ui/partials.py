"""HTMX partial fragment routes for the Hassette Web UI."""

from fastapi import APIRouter, Query, Request
from starlette.responses import HTMLResponse

from hassette.web.dependencies import DataSyncDep
from hassette.web.ui import templates
from hassette.web.ui.context import alert_context

router = APIRouter()


@router.get("/partials/app-list", response_class=HTMLResponse)
async def app_list_partial(request: Request, data_sync: DataSyncDep) -> HTMLResponse:
    app_status = data_sync.get_app_status_snapshot()
    return templates.TemplateResponse(request, "partials/app_list.html", {"app_status": app_status})


@router.get("/partials/app-row/{app_key}", response_class=HTMLResponse)
async def app_row_partial(app_key: str, request: Request, data_sync: DataSyncDep) -> HTMLResponse:
    app_status = data_sync.get_app_status_snapshot()
    app = next((a for a in app_status.apps if a.app_key == app_key), None)
    return templates.TemplateResponse(request, "partials/app_row.html", {"app": app})


@router.get("/partials/log-entries", response_class=HTMLResponse)
async def log_entries_partial(
    request: Request,
    data_sync: DataSyncDep,
    level: str | None = None,
    app_key: str | None = None,
    limit: int = Query(default=100, ge=1, le=2000),  # pyright: ignore[reportCallInDefaultInitializer]
) -> HTMLResponse:
    logs = data_sync.get_recent_logs(limit=limit, app_key=app_key, level=level)
    show_app_column = not app_key
    return templates.TemplateResponse(
        request, "partials/log_entries.html", {"logs": logs, "show_app_column": show_app_column}
    )


@router.get("/partials/manifest-list", response_class=HTMLResponse)
async def manifest_list_partial(
    request: Request,
    data_sync: DataSyncDep,
    status: str | None = None,
) -> HTMLResponse:
    snapshot = data_sync.get_all_manifests_snapshot()
    manifests = snapshot.manifests
    if status:
        manifests = [m for m in manifests if m.status == status]
    return templates.TemplateResponse(request, "partials/manifest_list.html", {"manifests": manifests})


@router.get("/partials/scheduler-jobs", response_class=HTMLResponse)
async def scheduler_jobs_partial(
    request: Request,
    data_sync: DataSyncDep,
    owner: str | None = None,
) -> HTMLResponse:
    app_owner_map = data_sync.get_user_app_owner_map()
    instance_owner_map = data_sync.get_instance_owner_map()
    all_jobs = await data_sync.get_scheduled_jobs(owner=owner)
    jobs = [j for j in all_jobs if j["owner"] in app_owner_map]
    return templates.TemplateResponse(
        request,
        "partials/scheduler_jobs.html",
        {"jobs": jobs, "app_owner_map": app_owner_map, "instance_owner_map": instance_owner_map},
    )


@router.get("/partials/scheduler-history", response_class=HTMLResponse)
async def scheduler_history_partial(
    request: Request,
    data_sync: DataSyncDep,
    owner: str | None = None,
    limit: int = 50,
) -> HTMLResponse:
    app_owner_map = data_sync.get_user_app_owner_map()
    instance_owner_map = data_sync.get_instance_owner_map()
    history_all = data_sync.get_job_execution_history(limit=limit, owner=owner)
    history = [h for h in history_all if h["owner"] in app_owner_map]
    return templates.TemplateResponse(
        request,
        "partials/scheduler_history.html",
        {"history": history, "app_owner_map": app_owner_map, "instance_owner_map": instance_owner_map},
    )


@router.get("/partials/bus-listeners", response_class=HTMLResponse)
async def bus_listeners_partial(
    request: Request,
    data_sync: DataSyncDep,
    owner: str | None = None,
) -> HTMLResponse:
    app_owner_map = data_sync.get_user_app_owner_map()
    instance_owner_map = data_sync.get_instance_owner_map()
    all_listeners = data_sync.get_listener_metrics(owner=owner)
    listeners = [x for x in all_listeners if x["owner"] in app_owner_map]
    return templates.TemplateResponse(
        request,
        "partials/bus_listeners.html",
        {"listeners": listeners, "app_owner_map": app_owner_map, "instance_owner_map": instance_owner_map},
    )


@router.get("/partials/dashboard-app-grid", response_class=HTMLResponse)
async def dashboard_app_grid_partial(request: Request, data_sync: DataSyncDep) -> HTMLResponse:
    snapshot = data_sync.get_all_manifests_snapshot()
    return templates.TemplateResponse(request, "partials/dashboard_app_grid.html", {"manifests": snapshot.manifests})


@router.get("/partials/dashboard-timeline", response_class=HTMLResponse)
async def dashboard_timeline_partial(request: Request, data_sync: DataSyncDep) -> HTMLResponse:
    events = data_sync.get_recent_events(limit=20)
    return templates.TemplateResponse(request, "partials/dashboard_timeline.html", {"events": events})


@router.get("/partials/dashboard-logs", response_class=HTMLResponse)
async def dashboard_logs_partial(request: Request, data_sync: DataSyncDep) -> HTMLResponse:
    logs = data_sync.get_recent_logs(limit=30)
    return templates.TemplateResponse(request, "partials/dashboard_logs.html", {"logs": logs})


@router.get("/partials/alert-failed-apps", response_class=HTMLResponse)
async def alert_failed_apps_partial(request: Request, data_sync: DataSyncDep) -> HTMLResponse:
    ctx = alert_context(data_sync)
    return templates.TemplateResponse(request, "partials/alert_failed_apps.html", ctx)


@router.get("/partials/app-detail-listeners/{app_key}", response_class=HTMLResponse)
async def app_detail_listeners_partial(app_key: str, request: Request, data_sync: DataSyncDep) -> HTMLResponse:
    instance_owner_map = data_sync.get_instance_owner_map()
    listeners = data_sync.get_listener_metrics(owner=app_key)
    return templates.TemplateResponse(
        request,
        "partials/app_detail_listeners.html",
        {"listeners": listeners, "instance_owner_map": instance_owner_map},
    )


@router.get("/partials/app-detail-jobs/{app_key}", response_class=HTMLResponse)
async def app_detail_jobs_partial(app_key: str, request: Request, data_sync: DataSyncDep) -> HTMLResponse:
    instance_owner_map = data_sync.get_instance_owner_map()
    jobs = await data_sync.get_scheduled_jobs(owner=app_key)
    return templates.TemplateResponse(
        request,
        "partials/app_detail_jobs.html",
        {"jobs": jobs, "instance_owner_map": instance_owner_map},
    )


@router.get("/partials/instance-listeners/{app_key}/{index}", response_class=HTMLResponse)
async def instance_listeners_partial(
    app_key: str, index: int, request: Request, data_sync: DataSyncDep
) -> HTMLResponse:
    listeners = data_sync.get_listener_metrics_for_instance(app_key, index)
    return templates.TemplateResponse(request, "partials/app_detail_listeners.html", {"listeners": listeners})


@router.get("/partials/instance-jobs/{app_key}/{index}", response_class=HTMLResponse)
async def instance_jobs_partial(app_key: str, index: int, request: Request, data_sync: DataSyncDep) -> HTMLResponse:
    jobs = await data_sync.get_scheduled_jobs_for_instance(app_key, index)
    return templates.TemplateResponse(request, "partials/app_detail_jobs.html", {"jobs": jobs})
