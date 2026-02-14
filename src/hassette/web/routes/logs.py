"""Log query endpoint."""

from typing import Annotated

from fastapi import APIRouter, Query

from hassette.web.dependencies import DataSyncDep
from hassette.web.models import LogEntryResponse

router = APIRouter(tags=["logs"])


@router.get("/logs/recent", response_model=list[LogEntryResponse])
async def get_logs(
    data_sync: DataSyncDep,
    limit: Annotated[int, Query(ge=1, le=2000)] = 100,
    app_key: Annotated[str | None, Query()] = None,
    level: Annotated[str | None, Query()] = None,
) -> list[dict]:
    return data_sync.get_recent_logs(limit=limit, app_key=app_key, level=level)
