"""Health and status endpoints."""

from fastapi import APIRouter, Response

from hassette.web.dependencies import RuntimeDep
from hassette.web.models import SystemStatusResponse

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=SystemStatusResponse,
    responses={503: {"model": SystemStatusResponse}},
)
async def get_health(runtime: RuntimeDep, response: Response) -> SystemStatusResponse:
    status_data = runtime.get_system_status()
    if status_data.status != "ok":
        response.status_code = 503
    return status_data
