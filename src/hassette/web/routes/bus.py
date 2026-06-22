"""Bus listener metrics endpoints."""

from typing import Annotated

from fastapi import APIRouter, Query, Response

from hassette.types.types import QuerySourceTier
from hassette.web.dependencies import SOURCE_TIER_PARAM, HassetteDep, TelemetryDep, db_degrades_to
from hassette.web.mappers import to_listener_with_summary
from hassette.web.models import ListenerWithSummary

router = APIRouter(tags=["bus"])


@router.get("/bus/listeners", response_model=list[ListenerWithSummary])
async def get_listener_metrics(
    telemetry: TelemetryDep,
    hassette: HassetteDep,
    response: Response,
    app_key: Annotated[str | None, Query()] = None,
    instance_index: Annotated[
        int,
        Query(description="App instance index. Defaults to 0. Multi-instance apps have indices 0..N-1."),
    ] = 0,
    since: float | None = Query(default=None),  # pyright: ignore[reportCallInDefaultInitializer]
    source_tier: QuerySourceTier = SOURCE_TIER_PARAM,
) -> list[ListenerWithSummary]:
    # Guard: app_key="" (empty string) must NOT fall through to the all-apps path.
    # The unified get_listener_summary uses `if app_key is not None` internally,
    # so only a genuine None triggers the full-table scan.
    # Category B: live_execution_counts() + the mapping depend on the query result and must be
    # skipped on DB failure (matches app_listeners) — keep them inside the with block.
    rows: list[ListenerWithSummary] = []
    with db_degrades_to(response):
        summaries = await telemetry.get_listener_summary(
            app_key=app_key,
            instance_index=instance_index,
            since=since,
            source_tier=source_tier,
        )
        live_counts = hassette.bus_service.live_execution_counts()
        rows = [to_listener_with_summary(ls, live_counts) for ls in summaries]
    return rows
