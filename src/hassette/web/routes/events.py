"""Event history endpoint."""

from typing import Annotated

from fastapi import APIRouter, Query

from hassette.web.dependencies import DataSyncDep

router = APIRouter(tags=["events"])


@router.get("/events/recent")
async def get_recent_events(
    data_sync: DataSyncDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[dict]:
    return data_sync.get_recent_events(limit=limit)
