"""Health and status endpoints."""

import typing

from fastapi import APIRouter, Depends, Response

from hassette.web.dependencies import get_data_sync, get_hassette
from hassette.web.models import SystemStatusResponse

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.core.data_sync_service import DataSyncService

router = APIRouter(tags=["health"])

HassetteDep = typing.Annotated["Hassette", Depends(get_hassette)]
DataSyncDep = typing.Annotated["DataSyncService", Depends(get_data_sync)]


@router.get("/health", response_model=SystemStatusResponse)
async def get_health(data_sync: DataSyncDep) -> SystemStatusResponse:
    return data_sync.get_system_status()


@router.get("/healthz")
async def healthz(hassette: HassetteDep) -> Response:
    """Backwards-compatible health endpoint matching the old HealthService contract."""
    from hassette.types.enums import ResourceStatus

    ws_running = hassette._websocket_service.status == ResourceStatus.RUNNING
    if ws_running:
        return Response(
            content='{"status":"ok","ws":"connected"}',
            media_type="application/json",
            status_code=200,
        )
    return Response(
        content='{"status":"degraded","ws":"disconnected"}',
        media_type="application/json",
        status_code=503,
    )
