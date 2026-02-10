"""HA services endpoint."""

import typing
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from hassette.web.dependencies import get_api

if typing.TYPE_CHECKING:
    from hassette.api import Api

router = APIRouter(tags=["services"])

ApiDep = typing.Annotated["Api", Depends(get_api)]


@router.get("/services")
async def get_services(api: ApiDep) -> dict[str, Any]:
    try:
        return await api.get_services()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch services from HA: {exc}") from exc
