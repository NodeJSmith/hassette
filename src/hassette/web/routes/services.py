"""HA services endpoint."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from hassette.web.dependencies import ApiDep

logger = logging.getLogger(__name__)

router = APIRouter(tags=["services"])


@router.get("/services")
async def get_services(api: ApiDep) -> dict[str, Any]:
    try:
        return await api.get_services()
    except Exception as exc:
        logger.warning("Failed to fetch services from HA", exc_info=True)
        raise HTTPException(status_code=502, detail="Failed to fetch services from Home Assistant") from exc
