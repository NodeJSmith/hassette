"""Full-page routes for the Hassette Web UI."""

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import HTMLResponse

from hassette.web.dependencies import DataSyncDep
from hassette.web.ui import templates
from hassette.web.ui.context import alert_context, base_context

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request, data_sync: DataSyncDep) -> HTMLResponse:
    manifest_snapshot = data_sync.get_all_manifests_snapshot()
    events = data_sync.get_recent_events(limit=20)
    logs = data_sync.get_recent_logs(limit=30)
    ctx = {
        **base_context("dashboard"),
        **alert_context(data_sync),
        "manifests": manifest_snapshot.manifests,
        "events": events,
        "logs": logs,
    }
    return templates.TemplateResponse(request, "pages/dashboard.html", ctx)


@router.get("/apps", response_class=HTMLResponse)
async def apps_page(request: Request, data_sync: DataSyncDep) -> HTMLResponse:
    manifest_snapshot = data_sync.get_all_manifests_snapshot()
    ctx = {
        **base_context("apps"),
        **alert_context(data_sync),
        "manifest_snapshot": manifest_snapshot,
    }
    return templates.TemplateResponse(request, "pages/apps.html", ctx)


@router.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request, data_sync: DataSyncDep) -> HTMLResponse:
    logs = data_sync.get_recent_logs(limit=100)
    manifest_snapshot = data_sync.get_all_manifests_snapshot()
    app_keys = sorted(m.app_key for m in manifest_snapshot.manifests)
    ctx = {
        **base_context("logs"),
        **alert_context(data_sync),
        "logs": logs,
        "app_keys": app_keys,
    }
    return templates.TemplateResponse(request, "pages/logs.html", ctx)


@router.get("/scheduler", response_class=HTMLResponse)
async def scheduler_page(request: Request, data_sync: DataSyncDep) -> HTMLResponse:
    app_owner_map = data_sync.get_user_app_owner_map()
    instance_owner_map = data_sync.get_instance_owner_map()
    all_jobs = await data_sync.get_scheduled_jobs()
    jobs = [j for j in all_jobs if j["owner"] in app_owner_map]
    history_all = data_sync.get_job_execution_history(limit=50)
    history = [h for h in history_all if h["owner"] in app_owner_map]
    owners = sorted({j["owner"] for j in jobs})
    ctx = {
        **base_context("scheduler"),
        **alert_context(data_sync),
        "jobs": jobs,
        "history": history,
        "owners": owners,
        "app_owner_map": app_owner_map,
        "instance_owner_map": instance_owner_map,
    }
    return templates.TemplateResponse(request, "pages/scheduler.html", ctx)


@router.get("/bus", response_class=HTMLResponse)
async def bus_page(request: Request, data_sync: DataSyncDep) -> HTMLResponse:
    app_owner_map = data_sync.get_user_app_owner_map()
    instance_owner_map = data_sync.get_instance_owner_map()
    all_listeners = data_sync.get_listener_metrics()
    listeners = [x for x in all_listeners if x["owner"] in app_owner_map]
    owners = sorted({x["owner"] for x in listeners})
    ctx = {
        **base_context("bus"),
        **alert_context(data_sync),
        "listeners": listeners,
        "owners": owners,
        "app_owner_map": app_owner_map,
        "instance_owner_map": instance_owner_map,
    }
    return templates.TemplateResponse(request, "pages/bus.html", ctx)


@router.get("/apps/{app_key}", response_class=HTMLResponse)
async def app_detail_page(app_key: str, request: Request, data_sync: DataSyncDep) -> HTMLResponse:
    manifest_snapshot = data_sync.get_all_manifests_snapshot()
    manifest = next((m for m in manifest_snapshot.manifests if m.app_key == app_key), None)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"App '{app_key}' not found")

    instance = manifest.instances[0] if manifest.instances else None
    instance_index = instance.index if instance else 0
    owner_id = instance.owner_id if instance else None
    listeners = data_sync.get_listener_metrics_for_instance(app_key, instance_index) if owner_id else []
    jobs = await data_sync.get_scheduled_jobs_for_instance(app_key, instance_index) if owner_id else []
    logs = data_sync.get_recent_logs(app_key=app_key, limit=50)
    ctx = {
        **base_context("apps"),
        **alert_context(data_sync),
        "manifest": manifest,
        "instance": instance,
        "app_key": app_key,
        "instance_index": instance_index,
        "owner_id": owner_id,
        "listeners": listeners,
        "jobs": jobs,
        "logs": logs,
        "show_app_column": False,
        "is_multi_instance": manifest.instance_count > 1,
    }
    return templates.TemplateResponse(request, "pages/app_instance_detail.html", ctx)


@router.get("/apps/{app_key}/{index}", response_class=HTMLResponse)
async def app_instance_detail_page(app_key: str, index: int, request: Request, data_sync: DataSyncDep) -> HTMLResponse:
    manifest_snapshot = data_sync.get_all_manifests_snapshot()
    manifest = next((m for m in manifest_snapshot.manifests if m.app_key == app_key), None)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"App '{app_key}' not found")

    instance = next((i for i in manifest.instances if i.index == index), None)
    if instance is None:
        raise HTTPException(status_code=404, detail=f"Instance {index} of '{app_key}' not found")

    owner_id = instance.owner_id
    listeners = data_sync.get_listener_metrics_for_instance(app_key, index) if owner_id else []
    jobs = await data_sync.get_scheduled_jobs_for_instance(app_key, index) if owner_id else []
    logs = data_sync.get_recent_logs(app_key=app_key, limit=50)
    ctx = {
        **base_context("apps"),
        **alert_context(data_sync),
        "manifest": manifest,
        "instance": instance,
        "app_key": app_key,
        "instance_index": index,
        "owner_id": owner_id,
        "listeners": listeners,
        "jobs": jobs,
        "logs": logs,
        "show_app_column": False,
        "is_multi_instance": manifest.instance_count > 1,
    }
    return templates.TemplateResponse(request, "pages/app_instance_detail.html", ctx)
