"""Bus listener metrics endpoints."""

from typing import Annotated

from fastapi import APIRouter, Query

from hassette.web.dependencies import RuntimeDep, TelemetryDep
from hassette.web.models import BusMetricsSummaryResponse, ListenerWithSummary
from hassette.web.telemetry_helpers import safe_session_id, to_listener_with_summary
from hassette.web.utils import gather_all_listeners

router = APIRouter(tags=["bus"])


@router.get("/bus/listeners", response_model=list[ListenerWithSummary])
async def get_listener_metrics(
    runtime: RuntimeDep,
    telemetry: TelemetryDep,
    app_key: Annotated[str | None, Query()] = None,
    instance_index: Annotated[int, Query()] = 0,
) -> list[ListenerWithSummary]:
    session_id = safe_session_id(runtime)
    if not app_key:
        summaries = await gather_all_listeners(runtime, telemetry, session_id=session_id)
    else:
        summaries = await telemetry.get_listener_summary(
            app_key=app_key, instance_index=instance_index, session_id=session_id
        )
    return [to_listener_with_summary(ls) for ls in summaries]


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
