"""Full-page routes for the Hassette Web UI."""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import HTMLResponse

from hassette.web.dependencies import RuntimeDep, SchedulerDep, TelemetryDep
from hassette.web.ui import templates
from hassette.web.ui.context import alert_context, base_context, job_to_dict

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request, runtime: RuntimeDep) -> HTMLResponse:
    manifest_snapshot = runtime.get_all_manifests_snapshot()
    events = runtime.get_recent_events(limit=20)
    logs = runtime.get_recent_logs(limit=30)
    ctx = {
        **base_context("dashboard"),
        **alert_context(runtime),
        "manifests": manifest_snapshot.manifests,
        "events": events,
        "logs": logs,
    }
    return templates.TemplateResponse(request, "pages/dashboard.html", ctx)


@router.get("/apps", response_class=HTMLResponse)
async def apps_page(request: Request, runtime: RuntimeDep) -> HTMLResponse:
    manifest_snapshot = runtime.get_all_manifests_snapshot()
    ctx = {
        **base_context("apps"),
        **alert_context(runtime),
        "manifest_snapshot": manifest_snapshot,
    }
    return templates.TemplateResponse(request, "pages/apps.html", ctx)


@router.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request, runtime: RuntimeDep) -> HTMLResponse:
    logs = runtime.get_recent_logs(limit=100)
    manifest_snapshot = runtime.get_all_manifests_snapshot()
    app_keys = sorted(m.app_key for m in manifest_snapshot.manifests)
    ctx = {
        **base_context("logs"),
        **alert_context(runtime),
        "logs": logs,
        "app_keys": app_keys,
    }
    return templates.TemplateResponse(request, "pages/logs.html", ctx)


@router.get("/scheduler", response_class=HTMLResponse)
async def scheduler_page(request: Request, runtime: RuntimeDep, scheduler: SchedulerDep) -> HTMLResponse:
    all_jobs = await scheduler.get_all_jobs()
    jobs = [job_to_dict(j) for j in all_jobs]
    manifest_snapshot = runtime.get_all_manifests_snapshot()
    app_keys = sorted(m.app_key for m in manifest_snapshot.manifests)
    ctx = {
        **base_context("scheduler"),
        **alert_context(runtime),
        "jobs": jobs,
        "history": [],
        "app_keys": app_keys,
    }
    return templates.TemplateResponse(request, "pages/scheduler.html", ctx)


@router.get("/bus", response_class=HTMLResponse)
async def bus_page(request: Request, runtime: RuntimeDep, telemetry: TelemetryDep) -> HTMLResponse:
    manifest_snapshot = runtime.get_all_manifests_snapshot()
    app_keys = sorted(m.app_key for m in manifest_snapshot.manifests)
    tasks = [
        telemetry.get_listener_summary(app_key=manifest.app_key, instance_index=instance.index)
        for manifest in manifest_snapshot.manifests
        for instance in manifest.instances
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    listeners = []
    for result in results:
        if isinstance(result, BaseException):
            logger.warning("Telemetry query failed for bus page: %s", result)
        elif isinstance(result, list):
            listeners.extend(result)
    ctx = {
        **base_context("bus"),
        **alert_context(runtime),
        "listeners": listeners,
        "app_keys": app_keys,
    }
    return templates.TemplateResponse(request, "pages/bus.html", ctx)


@router.get("/apps/{app_key}", response_class=HTMLResponse)
async def app_detail_page(
    app_key: str,
    request: Request,
    runtime: RuntimeDep,
    telemetry: TelemetryDep,
    scheduler: SchedulerDep,
) -> HTMLResponse:
    manifest_snapshot = runtime.get_all_manifests_snapshot()
    manifest = next((m for m in manifest_snapshot.manifests if m.app_key == app_key), None)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"App '{app_key}' not found")

    instance = manifest.instances[0] if manifest.instances else None
    instance_index = instance.index if instance else 0
    owner_id = instance.owner_id if instance else None
    listeners = await telemetry.get_listener_summary(app_key=app_key, instance_index=instance_index)
    all_jobs = await scheduler.get_all_jobs()
    jobs = [
        job_to_dict(j, app_key=app_key, instance_index=instance_index)
        for j in all_jobs
        if owner_id and j.owner == owner_id
    ]
    logs = runtime.get_recent_logs(app_key=app_key, limit=50)
    ctx = {
        **base_context("apps"),
        **alert_context(runtime),
        "manifest": manifest,
        "instance": instance,
        "app_key": app_key,
        "instance_index": instance_index,
        "listeners": listeners,
        "jobs": jobs,
        "logs": logs,
        "show_app_column": False,
        "is_multi_instance": manifest.instance_count > 1,
    }
    return templates.TemplateResponse(request, "pages/app_instance_detail.html", ctx)


@router.get("/apps/{app_key}/{index}", response_class=HTMLResponse)
async def app_instance_detail_page(
    app_key: str,
    index: int,
    request: Request,
    runtime: RuntimeDep,
    telemetry: TelemetryDep,
    scheduler: SchedulerDep,
) -> HTMLResponse:
    manifest_snapshot = runtime.get_all_manifests_snapshot()
    manifest = next((m for m in manifest_snapshot.manifests if m.app_key == app_key), None)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"App '{app_key}' not found")

    instance = next((i for i in manifest.instances if i.index == index), None)
    if instance is None:
        raise HTTPException(status_code=404, detail=f"Instance {index} of '{app_key}' not found")

    listeners = await telemetry.get_listener_summary(app_key=app_key, instance_index=index)
    all_jobs = await scheduler.get_all_jobs()
    jobs = [
        job_to_dict(j, app_key=app_key, instance_index=index)
        for j in all_jobs
        if instance.owner_id and j.owner == instance.owner_id
    ]
    logs = runtime.get_recent_logs(app_key=app_key, limit=50)
    ctx = {
        **base_context("apps"),
        **alert_context(runtime),
        "manifest": manifest,
        "instance": instance,
        "app_key": app_key,
        "instance_index": index,
        "listeners": listeners,
        "jobs": jobs,
        "logs": logs,
        "show_app_column": False,
        "is_multi_instance": manifest.instance_count > 1,
    }
    return templates.TemplateResponse(request, "pages/app_instance_detail.html", ctx)
