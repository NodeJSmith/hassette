"""Log query endpoint."""

import typing
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from hassette.web.dependencies import get_data_sync
from hassette.web.models import LogEntryResponse

if typing.TYPE_CHECKING:
    from hassette.core.data_sync_service import DataSyncService

router = APIRouter(tags=["logs"])

DataSyncDep = typing.Annotated["DataSyncService", Depends(get_data_sync)]


@router.get("/logs", response_model=list[LogEntryResponse])
async def get_logs(
    data_sync: DataSyncDep,
    limit: Annotated[int, Query(ge=1, le=2000)] = 100,
    app_key: Annotated[str | None, Query()] = None,
    level: Annotated[str | None, Query()] = None,
) -> list[dict]:
    return data_sync.get_recent_logs(limit=limit, app_key=app_key, level=level)
