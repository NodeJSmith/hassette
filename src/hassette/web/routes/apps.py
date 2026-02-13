"""App management endpoints."""

import logging
import typing

from fastapi import APIRouter, HTTPException

from hassette.web.dependencies import DataSyncDep, HassetteDep

if typing.TYPE_CHECKING:
    from hassette import Hassette
from hassette.web.models import AppInstanceResponse, AppManifestListResponse, AppStatusResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["apps"])


@router.get("/apps", response_model=AppStatusResponse)
async def get_apps(data_sync: DataSyncDep) -> AppStatusResponse:
    return data_sync.get_app_status_snapshot()


@router.get("/apps/manifests", response_model=AppManifestListResponse)
async def get_app_manifests(data_sync: DataSyncDep) -> AppManifestListResponse:
    return data_sync.get_all_manifests_snapshot()


@router.get("/apps/{app_key}", response_model=AppInstanceResponse)
async def get_app(app_key: str, data_sync: DataSyncDep) -> AppInstanceResponse:
    snapshot = data_sync.get_app_status_snapshot()
    for app in snapshot.apps:
        if app.app_key == app_key:
            return app
    raise HTTPException(status_code=404, detail=f"App {app_key} not found")


def _check_reload_allowed(hassette: "Hassette") -> None:
    if not (hassette.config.dev_mode or hassette.config.allow_reload_in_prod):
        raise HTTPException(status_code=403, detail="App management is disabled in production mode")


@router.post("/apps/{app_key}/start", status_code=202)
async def start_app(app_key: str, hassette: HassetteDep) -> dict[str, str]:
    _check_reload_allowed(hassette)
    try:
        await hassette.app_handler.start_app(app_key)
    except Exception as exc:
        logger.warning("Failed to start app %s", app_key, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to start app") from exc
    return {"status": "accepted", "app_key": app_key, "action": "start"}


@router.post("/apps/{app_key}/stop", status_code=202)
async def stop_app(app_key: str, hassette: HassetteDep) -> dict[str, str]:
    _check_reload_allowed(hassette)
    try:
        await hassette.app_handler.stop_app(app_key)
    except Exception as exc:
        logger.warning("Failed to stop app %s", app_key, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to stop app") from exc
    return {"status": "accepted", "app_key": app_key, "action": "stop"}


@router.post("/apps/{app_key}/reload", status_code=202)
async def reload_app(app_key: str, hassette: HassetteDep) -> dict[str, str]:
    _check_reload_allowed(hassette)
    try:
        await hassette.app_handler.reload_app(app_key)
    except Exception as exc:
        logger.warning("Failed to reload app %s", app_key, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to reload app") from exc
    return {"status": "accepted", "app_key": app_key, "action": "reload"}
