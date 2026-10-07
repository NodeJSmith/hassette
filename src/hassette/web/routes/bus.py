"""Bus listener metrics endpoints."""

from typing import Annotated

from fastapi import APIRouter, Query
from hassette_wire import ListenerSummary, ProblemCode

from hassette.web.dependencies import HassetteDep, TelemetryDep, TelemetryFiltersDep
from hassette.web.errors import problem_responses
from hassette.web.mappers import listener_summary_from

router = APIRouter(tags=["bus"])


@router.get(
    "/bus/listeners",
    response_model=list[ListenerSummary],
    responses=problem_responses(ProblemCode.TELEMETRY_UNAVAILABLE),
)
async def get_listener_metrics(
    telemetry: TelemetryDep,
    hassette: HassetteDep,
    filters: TelemetryFiltersDep,
    app_key: Annotated[str | None, Query()] = None,
) -> list[ListenerSummary]:
    # Guard: app_key="" (empty string) must NOT fall through to the all-apps path.
    # The unified get_listener_summary uses `if app_key is not None` internally,
    # so only a genuine None triggers the full-table scan.
    summaries = await telemetry.get_listener_summary(app_key=app_key, **filters.query_kwargs)
    live_counts = hassette.bus_service.live_execution_counts()
    return [listener_summary_from(row, live_counts) for row in summaries]
