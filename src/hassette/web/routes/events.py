"""Event history endpoint."""

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, Query

from hassette.web.dependencies import get_data_sync

if TYPE_CHECKING:
    from hassette.core.data_sync_service import DataSyncService

router = APIRouter(tags=["events"])

DataSyncDep = Annotated["DataSyncService", Depends(get_data_sync)]


@router.get("/events/recent")
async def get_recent_events(
    data_sync: DataSyncDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[dict]:
    return data_sync.get_recent_events(limit=limit)
