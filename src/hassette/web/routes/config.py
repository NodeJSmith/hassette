"""Configuration endpoint."""

import typing
from typing import Any

from fastapi import APIRouter, Depends

from hassette.web.dependencies import get_hassette

if typing.TYPE_CHECKING:
    from hassette import Hassette

router = APIRouter(tags=["config"])

HassetteDep = typing.Annotated["Hassette", Depends(get_hassette)]


@router.get("/config")
async def get_config(hassette: HassetteDep) -> dict[str, Any]:
    """Return sanitized hassette configuration (token redacted)."""
    return hassette.config.model_dump(exclude={"token"})
