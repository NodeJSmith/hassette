"""Bus listener metrics endpoints."""

from typing import Annotated

from fastapi import APIRouter, Query

from hassette.web.dependencies import DataSyncDep
from hassette.web.models import BusMetricsSummaryResponse, ListenerMetricsResponse

router = APIRouter(tags=["bus"])


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
