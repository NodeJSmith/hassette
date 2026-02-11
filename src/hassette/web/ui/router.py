"""Full-page routes for the Hassette Web UI."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
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
    app_status = data_sync.get_app_status_snapshot()
    ctx = {
        **base_context("apps"),
        "app_status": app_status,
    }
    return templates.TemplateResponse(request, "pages/apps.html", ctx)


@router.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request, data_sync: DataSyncDep) -> HTMLResponse:
    logs = data_sync.get_recent_logs(limit=100)
    app_status = data_sync.get_app_status_snapshot()
    app_keys = sorted({app.app_key for app in app_status.apps})
    ctx = {
        **base_context("logs"),
        "logs": logs,
        "app_keys": app_keys,
    }
    return templates.TemplateResponse(request, "pages/logs.html", ctx)
