"""Full-page routes for the Hassette Web UI."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.responses import HTMLResponse

from hassette.core.data_sync_service import DataSyncService
from hassette.web.dependencies import get_data_sync
from hassette.web.ui import templates
from hassette.web.ui.context import base_context

DataSyncDep = Annotated[DataSyncService, Depends(get_data_sync)]

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request, data_sync: DataSyncDep) -> HTMLResponse:
    status = data_sync.get_system_status()
    app_status = data_sync.get_app_status_snapshot()
    events = data_sync.get_recent_events(limit=10)
    bus_metrics = data_sync.get_bus_metrics_summary()
    ctx = {
        **base_context("dashboard"),
        "status": status,
        "app_status": app_status,
        "events": events,
        "bus_metrics": bus_metrics,
    }
    return templates.TemplateResponse(request, "pages/dashboard.html", ctx)


@router.get("/apps", response_class=HTMLResponse)
async def apps_page(request: Request, data_sync: DataSyncDep) -> HTMLResponse:
    manifest_snapshot = data_sync.get_all_manifests_snapshot()
    ctx = {
        **base_context("apps"),
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
        "logs": logs,
        "app_keys": app_keys,
    }
    return templates.TemplateResponse(request, "pages/logs.html", ctx)


@router.get("/scheduler", response_class=HTMLResponse)
async def scheduler_page(request: Request, data_sync: DataSyncDep) -> HTMLResponse:
    jobs = await data_sync.get_scheduled_jobs()
    history = data_sync.get_job_execution_history(limit=50)
    owners = sorted({j["owner"] for j in jobs})
    ctx = {
        **base_context("scheduler"),
        "jobs": jobs,
        "history": history,
        "owners": owners,
    }
    return templates.TemplateResponse(request, "pages/scheduler.html", ctx)


@router.get("/entities", response_class=HTMLResponse)
async def entities_page(request: Request, data_sync: DataSyncDep) -> HTMLResponse:
    all_states = data_sync.get_all_entity_states()
    domains = sorted({eid.split(".")[0] for eid in all_states})
    ctx = {
        **base_context("entities"),
        "domains": domains,
        "entity_count": len(all_states),
    }
    return templates.TemplateResponse(request, "pages/entities.html", ctx)


@router.get("/apps/{app_key}", response_class=HTMLResponse)
async def app_detail_page(app_key: str, request: Request, data_sync: DataSyncDep) -> HTMLResponse:
    manifest_snapshot = data_sync.get_all_manifests_snapshot()
    manifest = next((m for m in manifest_snapshot.manifests if m.app_key == app_key), None)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"App '{app_key}' not found")

    listeners = data_sync.get_listener_metrics(owner=app_key)
    jobs = await data_sync.get_scheduled_jobs(owner=app_key)
    logs = data_sync.get_recent_logs(app_key=app_key, limit=50)
    ctx = {
        **base_context("apps"),
        "manifest": manifest,
        "app_key": app_key,
        "listeners": listeners,
        "jobs": jobs,
        "logs": logs,
    }
    return templates.TemplateResponse(request, "pages/app_detail.html", ctx)
