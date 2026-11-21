"""Bus listener metrics endpoints."""

from typing import Annotated

from fastapi import APIRouter, Query
from hassette_wire import ListenerSummary, ProblemCode

from hassette.web.dependencies import HassetteDep, TelemetryDep, TelemetryFiltersDep
from hassette.web.errors import problem_responses
from hassette.web.utils import listener_summaries

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
    """Return per-listener invocation metrics, optionally scoped to one app, merged with live execution counts."""
    return await listener_summaries(telemetry, hassette, app_key, filters)
