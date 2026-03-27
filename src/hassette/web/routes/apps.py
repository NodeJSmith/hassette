"""App management endpoints."""

import logging

from fastapi import APIRouter, HTTPException

from hassette.web.dependencies import HassetteDep, RuntimeDep
from hassette.web.models import ActionResponse, AppManifestListResponse, AppStatusResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["apps"])


@router.get("/apps", response_model=AppStatusResponse)
async def get_apps(runtime: RuntimeDep) -> AppStatusResponse:
    return runtime.get_app_status_snapshot()


@router.get("/apps/manifests", response_model=AppManifestListResponse)
async def get_app_manifests(runtime: RuntimeDep) -> AppManifestListResponse:
    return runtime.get_all_manifests_snapshot()


@router.post("/apps/{app_key}/start", status_code=202, response_model=ActionResponse)
async def start_app(app_key: str, hassette: HassetteDep) -> ActionResponse:
    try:
        await hassette.app_handler.start_app(app_key)
    except Exception as exc:
        logger.warning("Failed to start app %s", app_key, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to start app") from exc
    return ActionResponse(status="accepted", app_key=app_key, action="start")


@router.post("/apps/{app_key}/stop", status_code=202, response_model=ActionResponse)
async def stop_app(app_key: str, hassette: HassetteDep) -> ActionResponse:
    try:
        await hassette.app_handler.stop_app(app_key)
    except Exception as exc:
        logger.warning("Failed to stop app %s", app_key, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to stop app") from exc
    return ActionResponse(status="accepted", app_key=app_key, action="stop")


@router.post("/apps/{app_key}/reload", status_code=202, response_model=ActionResponse)
async def reload_app(app_key: str, hassette: HassetteDep) -> ActionResponse:
    try:
        await hassette.app_handler.reload_app(app_key)
    except Exception as exc:
        logger.warning("Failed to reload app %s", app_key, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to reload app") from exc
    return ActionResponse(status="accepted", app_key=app_key, action="reload")
