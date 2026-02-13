"""Health and status endpoints."""

from fastapi import APIRouter, Response

from hassette.web.dependencies import DataSyncDep, HassetteDep
from hassette.web.models import SystemStatusResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=SystemStatusResponse)
async def get_health(data_sync: DataSyncDep) -> SystemStatusResponse:
    return data_sync.get_system_status()


@router.get("/healthz")
async def healthz(hassette: HassetteDep) -> Response:
    """Backwards-compatible health endpoint matching the old HealthService contract."""
    from hassette.types.enums import ResourceStatus

    ws_running = hassette.websocket_service.status == ResourceStatus.RUNNING
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
