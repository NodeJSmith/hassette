"""Configuration endpoint."""

from fastapi import APIRouter

from hassette.web.dependencies import HassetteDep
from hassette.web.mappers import config_response_from
from hassette.web.models import ConfigResponse

router = APIRouter(tags=["config"])


@router.get("/config", response_model=ConfigResponse)
async def get_config(hassette: HassetteDep) -> ConfigResponse:
    """Return sanitized hassette configuration organized by config group."""
    return config_response_from(hassette.config)
