"""App management endpoints."""

import re
from logging import getLogger

from fastapi import APIRouter, HTTPException

from hassette.web.dependencies import HassetteDep, RuntimeDep
from hassette.web.mappers import app_manifest_list_response_from, app_status_response_from
from hassette.web.models import (
    ActionResponse,
    AppConfigResponse,
    AppManifestListResponse,
    AppSourceResponse,
    AppStatusResponse,
)

LOGGER = getLogger(__name__)

_VALID_APP_KEY = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.]{0,127}$")

router = APIRouter(tags=["apps"])


def _validate_app_key(app_key: str) -> None:
    if not _VALID_APP_KEY.match(app_key):
        raise HTTPException(status_code=400, detail=f"Invalid app_key: {app_key!r}")


def _require_known_app(app_key: str, hassette: HassetteDep) -> None:
    if hassette.app_handler.registry.get_manifest(app_key) is None:
        raise HTTPException(status_code=404, detail=f"App {app_key!r} not found")


@router.get("/apps", response_model=AppStatusResponse)
async def get_apps(runtime: RuntimeDep) -> AppStatusResponse:
    return app_status_response_from(runtime.get_app_status_snapshot())


@router.get("/apps/manifests", response_model=AppManifestListResponse)
async def get_app_manifests(runtime: RuntimeDep) -> AppManifestListResponse:
    return app_manifest_list_response_from(runtime.get_all_manifests_snapshot())


@router.post("/apps/{app_key}/start", status_code=202, response_model=ActionResponse)
async def start_app(app_key: str, hassette: HassetteDep) -> ActionResponse:
    _validate_app_key(app_key)
    _require_known_app(app_key, hassette)
    try:
        await hassette.app_handler.start_app(app_key)
    except (ValueError, RuntimeError) as exc:
        LOGGER.warning("Failed to start app %s", app_key, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to start app") from exc
    return ActionResponse(status="accepted", app_key=app_key, action="start")


@router.post("/apps/{app_key}/stop", status_code=202, response_model=ActionResponse)
async def stop_app(app_key: str, hassette: HassetteDep) -> ActionResponse:
    _validate_app_key(app_key)
    _require_known_app(app_key, hassette)
    try:
        await hassette.app_handler.stop_app(app_key)
    except (ValueError, RuntimeError) as exc:
        LOGGER.warning("Failed to stop app %s", app_key, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to stop app") from exc
    return ActionResponse(status="accepted", app_key=app_key, action="stop")


@router.post("/apps/{app_key}/reload", status_code=202, response_model=ActionResponse)
async def reload_app(app_key: str, hassette: HassetteDep) -> ActionResponse:
    _validate_app_key(app_key)
    _require_known_app(app_key, hassette)
    try:
        await hassette.app_handler.reload_app(app_key)
    except (ValueError, RuntimeError) as exc:
        LOGGER.warning("Failed to reload app %s", app_key, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to reload app") from exc
    return ActionResponse(status="accepted", app_key=app_key, action="reload")


@router.get("/apps/{app_key}/config", response_model=AppConfigResponse)
async def get_app_config(app_key: str, hassette: HassetteDep) -> AppConfigResponse:
    """Return the raw app configuration for the given app key."""
    _validate_app_key(app_key)
    manifest = hassette.app_handler.registry.get_manifest(app_key)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"App {app_key!r} not found")
    return AppConfigResponse(
        app_key=app_key,
        filename=manifest.filename,
        class_name=manifest.class_name,
        enabled=manifest.enabled,
        app_config=manifest.app_config,
    )


@router.get("/apps/{app_key}/source", response_model=AppSourceResponse)
async def get_app_source(app_key: str, hassette: HassetteDep) -> AppSourceResponse:
    """Return the source code of the app file for the given app key."""
    _validate_app_key(app_key)
    manifest = hassette.app_handler.registry.get_manifest(app_key)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"App {app_key!r} not found")

    # Path traversal protection: full_path must resolve within the manifest's app_dir
    try:
        resolved = manifest.full_path.resolve()
        app_dir_resolved = manifest.app_dir.resolve()
    except Exception as exc:
        LOGGER.warning("Failed to resolve paths for app %s", app_key, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to resolve app path") from exc

    if not resolved.is_relative_to(app_dir_resolved):
        LOGGER.warning(
            "Path traversal attempt for app %s: %s is not within %s",
            app_key,
            resolved,
            app_dir_resolved,
        )
        raise HTTPException(status_code=403, detail="Path traversal not allowed")

    if not resolved.exists():
        raise HTTPException(status_code=404, detail=f"Source file not found for app {app_key!r}")

    content = resolved.read_text(encoding="utf-8")
    return AppSourceResponse(
        app_key=app_key,
        filename=manifest.filename,
        content=content,
        line_count=len(content.splitlines()),
    )
