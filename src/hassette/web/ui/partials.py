"""HTMX partial fragment routes for the Hassette Web UI."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from starlette.responses import HTMLResponse

from hassette.core.data_sync_service import DataSyncService
from hassette.web.dependencies import get_data_sync
from hassette.web.ui import templates

DataSyncDep = Annotated[DataSyncService, Depends(get_data_sync)]

router = APIRouter()


@router.get("/partials/health-badge", response_class=HTMLResponse)
async def health_badge_partial(request: Request, data_sync: DataSyncDep) -> HTMLResponse:
    status = data_sync.get_system_status()
    return templates.TemplateResponse(request, "partials/health_badge.html", {"status": status})


@router.get("/partials/event-feed", response_class=HTMLResponse)
async def event_feed_partial(request: Request, data_sync: DataSyncDep) -> HTMLResponse:
    events = data_sync.get_recent_events(limit=10)
    return templates.TemplateResponse(request, "partials/event_feed.html", {"events": events})


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
    limit: int = 100,
) -> HTMLResponse:
    logs = data_sync.get_recent_logs(limit=limit, app_key=app_key, level=level)
    return templates.TemplateResponse(request, "partials/log_entries.html", {"logs": logs})
