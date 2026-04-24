"""HA services endpoint."""

from logging import getLogger
from typing import Any

from fastapi import APIRouter, HTTPException

from hassette.exceptions import FailedMessageError
from hassette.web.dependencies import ApiDep

LOGGER = getLogger(__name__)

router = APIRouter(tags=["services"])


@router.get("/services")
async def get_services(api: ApiDep) -> dict[str, Any]:
    try:
        return await api.get_services()
    except (OSError, TimeoutError, TypeError, RuntimeError, FailedMessageError) as exc:
        LOGGER.warning("Failed to fetch services from HA", exc_info=True)
        raise HTTPException(status_code=502, detail="Failed to fetch services from Home Assistant") from exc
