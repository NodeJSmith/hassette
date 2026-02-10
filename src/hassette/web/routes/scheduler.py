"""Scheduler jobs and execution history endpoints."""

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, Query

from hassette.web.dependencies import get_data_sync
from hassette.web.models import JobExecutionResponse, ScheduledJobResponse

if TYPE_CHECKING:
    from hassette.core.data_sync_service import DataSyncService

router = APIRouter(tags=["scheduler"])

DataSyncDep = Annotated["DataSyncService", Depends(get_data_sync)]


@router.get("/scheduler/jobs", response_model=list[ScheduledJobResponse])
async def get_scheduled_jobs(
    data_sync: DataSyncDep,
    owner: Annotated[str | None, Query()] = None,
) -> list[dict]:
    return await data_sync.get_scheduled_jobs(owner=owner)


@router.get("/scheduler/history", response_model=list[JobExecutionResponse])
async def get_job_history(
    data_sync: DataSyncDep,
    limit: Annotated[int, Query(ge=1, le=1000)] = 50,
    owner: Annotated[str | None, Query()] = None,
) -> list[dict]:
    return data_sync.get_job_execution_history(limit=limit, owner=owner)
