"""Bus listener metrics endpoints."""

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, Query

from hassette.web.dependencies import get_data_sync
from hassette.web.models import BusMetricsSummaryResponse, ListenerMetricsResponse

if TYPE_CHECKING:
    from hassette.core.data_sync_service import DataSyncService

router = APIRouter(tags=["bus"])

DataSyncDep = Annotated["DataSyncService", Depends(get_data_sync)]


@router.get("/bus/listeners", response_model=list[ListenerMetricsResponse])
async def get_listener_metrics(
    data_sync: DataSyncDep,
    owner: Annotated[str | None, Query()] = None,
) -> list[dict]:
    return data_sync.get_listener_metrics(owner=owner)


@router.get("/bus/metrics", response_model=BusMetricsSummaryResponse)
async def get_bus_metrics_summary(
    data_sync: DataSyncDep,
) -> BusMetricsSummaryResponse:
    return data_sync.get_bus_metrics_summary()
