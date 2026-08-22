"""Bus listener metrics endpoints."""

from typing import Annotated

from fastapi import APIRouter, Query, Response

from hassette.web.dependencies import HassetteDep, TelemetryDep, TelemetryFiltersDep, db_degrades_to
from hassette.web.mappers import to_listener_with_summary
from hassette.web.models import ListenerWithSummary

router = APIRouter(tags=["bus"])


@router.get("/bus/listeners", response_model=list[ListenerWithSummary])
async def get_listener_metrics(
    telemetry: TelemetryDep,
    hassette: HassetteDep,
    response: Response,
    filters: TelemetryFiltersDep,
    app_key: Annotated[str | None, Query()] = None,
) -> list[ListenerWithSummary]:
    # Guard: app_key="" (empty string) must NOT fall through to the all-apps path.
    # The unified get_listener_summary uses `if app_key is not None` internally,
    # so only a genuine None triggers the full-table scan.
    # live_execution_counts() and the mapping depend on the query result, so they stay
    # inside the with block to be skipped on DB failure.
    rows: list[ListenerWithSummary] = []
    with db_degrades_to(response):
        summaries = await telemetry.get_listener_summary(app_key=app_key, **filters.query_kwargs)
        live_counts = hassette.bus_service.live_execution_counts()
        rows = [to_listener_with_summary(ls, live_counts) for ls in summaries]
    return rows
