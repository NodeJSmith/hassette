"""Health and status endpoints."""

from fastapi import APIRouter, Response

from hassette.web.dependencies import RuntimeDep
from hassette.web.mappers import readiness_response_from, system_status_response_from
from hassette.web.models import LivenessResponse, ReadinessResponse, SystemStatusResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=SystemStatusResponse)
async def get_health(runtime: RuntimeDep) -> SystemStatusResponse:
    """Return the full system status. Always HTTP 200 while the process can serve."""
    return system_status_response_from(runtime.get_system_status())


@router.get("/health/live", response_model=LivenessResponse)
async def get_live() -> LivenessResponse:
    # Liveness is the absence of a check: reaching this line means the loop can serve.
    return LivenessResponse(status="live")


@router.get("/health/ready", response_model=ReadinessResponse, responses={503: {"model": ReadinessResponse}})
async def get_ready(runtime: RuntimeDep, response: Response) -> ReadinessResponse:
    """Return readiness status. 200 only when aggregate status is 'ok', else 503."""
    result = readiness_response_from(runtime.get_system_status())
    if not result.ready:
        response.status_code = 503
    return result
