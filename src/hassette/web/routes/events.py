"""Event history endpoint."""

from typing import Annotated

from fastapi import APIRouter, Query

from hassette.web.dependencies import RuntimeDep
from hassette.web.models import EventEntry

router = APIRouter(tags=["events"])


@router.get("/events/recent", response_model=list[EventEntry])
async def get_recent_events(
    runtime: RuntimeDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[EventEntry]:
    return [EventEntry.model_validate(e) for e in runtime.get_recent_events(limit=limit)]
