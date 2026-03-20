"""Full-page routes for the Hassette Web UI."""

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import HTMLResponse

from hassette.web.dependencies import RuntimeDep, TelemetryDep
from hassette.web.ui import templates
from hassette.web.ui.context import (
    alert_context,
    base_context,
    compute_app_grid_health,
    compute_health_metrics,
    format_handler_summary,
    safe_session_id,
)

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request, runtime: RuntimeDep, telemetry: TelemetryDep) -> HTMLResponse:
    manifest_snapshot = runtime.get_all_manifests_snapshot()
    system_status = runtime.get_system_status()

    # Session-scoped telemetry data.
    session_id = safe_session_id(runtime)
    global_summary = await telemetry.get_global_summary(session_id=session_id)
    recent_errors = await telemetry.get_recent_errors(since_ts=0, limit=10, session_id=session_id)
    session_summary = await telemetry.get_current_session_summary()

    # Compute per-app health metrics for the grid.
    app_health = await compute_app_grid_health(manifest_snapshot.manifests, telemetry, session_id=session_id)

    ctx = {
        **base_context("dashboard"),
        **alert_context(runtime),
        "manifests": manifest_snapshot.manifests,
        "system_status": system_status,
        "global_summary": global_summary,
        "recent_errors": recent_errors,
        "session_summary": session_summary,
        "app_health": app_health,
    }
    return templates.TemplateResponse(request, "pages/dashboard.html", ctx)


@router.get("/apps", response_class=HTMLResponse)
async def apps_page(request: Request, runtime: RuntimeDep) -> HTMLResponse:
    manifest_snapshot = runtime.get_all_manifests_snapshot()
    app_keys = sorted(m.app_key for m in manifest_snapshot.manifests)
    ctx = {
        **base_context("apps"),
        **alert_context(runtime),
        "manifest_snapshot": manifest_snapshot,
        "app_keys": app_keys,
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


@router.get("/apps/{app_key}", response_class=HTMLResponse)
async def app_detail_page(
    app_key: str,
    request: Request,
    runtime: RuntimeDep,
    telemetry: TelemetryDep,
) -> HTMLResponse:
    manifest_snapshot = runtime.get_all_manifests_snapshot()
    manifest = next((m for m in manifest_snapshot.manifests if m.app_key == app_key), None)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"App '{app_key}' not found")

    instance = manifest.instances[0] if manifest.instances else None
    instance_index = instance.index if instance else 0

    # Use telemetry for both listeners and jobs — filters by app_key + instance_index,
    # NOT by owner_id (which is None for stopped/failed apps).
    listeners = await telemetry.get_listener_summary(app_key=app_key, instance_index=instance_index)
    jobs = await telemetry.get_job_summary(app_key=app_key, instance_index=instance_index)

    handler_summaries = {ls.listener_id: format_handler_summary(ls) for ls in listeners}
    logs = runtime.get_recent_logs(app_key=app_key, limit=50)
    health = compute_health_metrics(listeners, jobs)

    ctx = {
        **base_context("apps"),
        **alert_context(runtime),
        "manifest": manifest,
        "instance": instance,
        "app_key": app_key,
        "instance_index": instance_index,
        "listeners": listeners,
        "handler_summaries": handler_summaries,
        "jobs": jobs,
        "logs": logs,
        "show_app_column": False,
        "is_multi_instance": manifest.instance_count > 1,
        "init_status": str(instance.status) if instance else manifest.status,
        **health,
    }
    return templates.TemplateResponse(request, "pages/app_detail.html", ctx)


@router.get("/apps/{app_key}/{index}", response_class=HTMLResponse)
async def app_instance_detail_page(
    app_key: str,
    index: int,
    request: Request,
    runtime: RuntimeDep,
    telemetry: TelemetryDep,
) -> HTMLResponse:
    manifest_snapshot = runtime.get_all_manifests_snapshot()
    manifest = next((m for m in manifest_snapshot.manifests if m.app_key == app_key), None)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"App '{app_key}' not found")

    instance = next((i for i in manifest.instances if i.index == index), None)
    if instance is None:
        raise HTTPException(status_code=404, detail=f"Instance {index} of '{app_key}' not found")

    # Use telemetry for both listeners and jobs — filters by app_key + instance_index.
    listeners = await telemetry.get_listener_summary(app_key=app_key, instance_index=index)
    jobs = await telemetry.get_job_summary(app_key=app_key, instance_index=index)

    handler_summaries = {ls.listener_id: format_handler_summary(ls) for ls in listeners}
    logs = runtime.get_recent_logs(app_key=app_key, limit=50)
    health = compute_health_metrics(listeners, jobs)

    ctx = {
        **base_context("apps"),
        **alert_context(runtime),
        "manifest": manifest,
        "instance": instance,
        "app_key": app_key,
        "instance_index": index,
        "listeners": listeners,
        "handler_summaries": handler_summaries,
        "jobs": jobs,
        "logs": logs,
        "show_app_column": False,
        "is_multi_instance": manifest.instance_count > 1,
        "init_status": str(instance.status),
        **health,
    }
    return templates.TemplateResponse(request, "pages/app_detail.html", ctx)
