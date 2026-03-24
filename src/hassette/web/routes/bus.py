"""Bus listener metrics endpoints."""

from typing import Annotated

from fastapi import APIRouter, Query

from hassette.web.dependencies import RuntimeDep, TelemetryDep
from hassette.web.models import BusMetricsSummaryResponse, ListenerMetricsResponse
from hassette.web.utils import gather_all_listeners

router = APIRouter(tags=["bus"])


@router.get("/bus/listeners", response_model=list[ListenerMetricsResponse])
async def get_listener_metrics(
    runtime: RuntimeDep,
    telemetry: TelemetryDep,
    app_key: Annotated[str | None, Query()] = None,
    instance_index: Annotated[int, Query()] = 0,
) -> list[ListenerMetricsResponse]:
    if not app_key:
        return await gather_all_listeners(runtime, telemetry)  # pyright: ignore[reportReturnType]
    return await telemetry.get_listener_summary(app_key=app_key, instance_index=instance_index)  # pyright: ignore[reportReturnType]


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
