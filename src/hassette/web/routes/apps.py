"""App management endpoints."""

import typing

from fastapi import APIRouter, Depends, HTTPException

from hassette.web.dependencies import get_data_sync, get_hassette
from hassette.web.models import AppInstanceResponse, AppStatusResponse

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.core.data_sync_service import DataSyncService

router = APIRouter(tags=["apps"])

HassetteDep = typing.Annotated["Hassette", Depends(get_hassette)]
DataSyncDep = typing.Annotated["DataSyncService", Depends(get_data_sync)]


@router.get("/apps", response_model=AppStatusResponse)
async def get_apps(data_sync: DataSyncDep) -> AppStatusResponse:
    return data_sync.get_app_status_snapshot()


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
        await hassette._app_handler.start_app(app_key)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "accepted", "app_key": app_key, "action": "start"}


@router.post("/apps/{app_key}/stop", status_code=202)
async def stop_app(app_key: str, hassette: HassetteDep) -> dict[str, str]:
    _check_reload_allowed(hassette)
    try:
        await hassette._app_handler.stop_app(app_key)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "accepted", "app_key": app_key, "action": "stop"}


@router.post("/apps/{app_key}/reload", status_code=202)
async def reload_app(app_key: str, hassette: HassetteDep) -> dict[str, str]:
    _check_reload_allowed(hassette)
    try:
        await hassette._app_handler.reload_app(app_key)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "accepted", "app_key": app_key, "action": "reload"}
