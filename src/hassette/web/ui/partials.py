"""HTMX partial fragment routes for the Hassette Web UI."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
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
    limit: Annotated[int, Query(default=100, ge=1, le=2000)] = 100,
) -> HTMLResponse:
    logs = data_sync.get_recent_logs(limit=limit, app_key=app_key, level=level)
    return templates.TemplateResponse(request, "partials/log_entries.html", {"logs": logs})


# --- New Phase 2 partials ---


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


@router.get("/partials/bus-metrics", response_class=HTMLResponse)
async def bus_metrics_partial(request: Request, data_sync: DataSyncDep) -> HTMLResponse:
    bus_metrics = data_sync.get_bus_metrics_summary()
    return templates.TemplateResponse(request, "partials/bus_metrics.html", {"bus_metrics": bus_metrics})


@router.get("/partials/apps-summary", response_class=HTMLResponse)
async def apps_summary_partial(request: Request, data_sync: DataSyncDep) -> HTMLResponse:
    app_status = data_sync.get_app_status_snapshot()
    return templates.TemplateResponse(request, "partials/apps_summary.html", {"app_status": app_status})


@router.get("/partials/scheduler-jobs", response_class=HTMLResponse)
async def scheduler_jobs_partial(
    request: Request,
    data_sync: DataSyncDep,
    owner: str | None = None,
) -> HTMLResponse:
    jobs = await data_sync.get_scheduled_jobs(owner=owner)
    return templates.TemplateResponse(request, "partials/scheduler_jobs.html", {"jobs": jobs})


@router.get("/partials/scheduler-history", response_class=HTMLResponse)
async def scheduler_history_partial(
    request: Request,
    data_sync: DataSyncDep,
    owner: str | None = None,
    limit: int = 50,
) -> HTMLResponse:
    history = data_sync.get_job_execution_history(limit=limit, owner=owner)
    return templates.TemplateResponse(request, "partials/scheduler_history.html", {"history": history})


@router.get("/partials/entity-list", response_class=HTMLResponse)
async def entity_list_partial(
    request: Request,
    data_sync: DataSyncDep,
    domain: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> HTMLResponse:
    all_states = data_sync.get_domain_states(domain) if domain else data_sync.get_all_entity_states()

    entities = sorted(all_states.items(), key=lambda kv: kv[0])

    if search:
        search_lower = search.lower()
        entities = [(eid, s) for eid, s in entities if search_lower in eid.lower()]

    total = len(entities)
    entities = entities[offset : offset + limit]

    return templates.TemplateResponse(
        request,
        "partials/entity_list.html",
        {"entities": entities, "total": total, "limit": limit, "offset": offset},
    )


@router.get("/partials/app-detail-listeners/{app_key}", response_class=HTMLResponse)
async def app_detail_listeners_partial(app_key: str, request: Request, data_sync: DataSyncDep) -> HTMLResponse:
    listeners = data_sync.get_listener_metrics(owner=app_key)
    return templates.TemplateResponse(request, "partials/app_detail_listeners.html", {"listeners": listeners})


@router.get("/partials/app-detail-jobs/{app_key}", response_class=HTMLResponse)
async def app_detail_jobs_partial(app_key: str, request: Request, data_sync: DataSyncDep) -> HTMLResponse:
    jobs = await data_sync.get_scheduled_jobs(owner=app_key)
    return templates.TemplateResponse(request, "partials/app_detail_jobs.html", {"jobs": jobs})
