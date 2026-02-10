"""Configuration endpoint."""

from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends

from hassette.web.dependencies import get_hassette

if TYPE_CHECKING:
    from hassette import Hassette

router = APIRouter(tags=["config"])

HassetteDep = Annotated["Hassette", Depends(get_hassette)]


@router.get("/config")
async def get_config(hassette: HassetteDep) -> dict[str, Any]:
    """Return sanitized hassette configuration (token redacted)."""
    return hassette.config.model_dump(exclude={"token"})
