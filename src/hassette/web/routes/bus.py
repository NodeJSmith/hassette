"""Bus listener metrics endpoints."""

from typing import Annotated

from fastapi import APIRouter, Query

from hassette.web.dependencies import TelemetryDep
from hassette.web.models import BusMetricsSummaryResponse, ListenerMetricsResponse

router = APIRouter(tags=["bus"])


@router.get("/bus/listeners", response_model=list[ListenerMetricsResponse])
async def get_listener_metrics(
    telemetry: TelemetryDep,
    app_key: Annotated[str | None, Query()] = None,
    instance_index: Annotated[int, Query()] = 0,
) -> list[dict]:
    if app_key is None:
        return []
    return await telemetry.get_listener_summary(app_key=app_key, instance_index=instance_index)


@router.get("/bus/metrics", response_model=BusMetricsSummaryResponse)
async def get_bus_metrics_summary() -> BusMetricsSummaryResponse:
    return BusMetricsSummaryResponse(
        total_listeners=0,
        total_invocations=0,
        total_successful=0,
        total_failed=0,
        total_di_failures=0,
        total_cancelled=0,
    )
