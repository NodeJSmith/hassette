"""Bus listener metrics endpoints."""

from logging import getLogger
from typing import Annotated

from fastapi import APIRouter, Query, Response

from hassette.types.types import QuerySourceTier
from hassette.web.dependencies import DB_ERRORS, SOURCE_TIER_PARAM, HassetteDep, TelemetryDep
from hassette.web.mappers import to_listener_with_summary
from hassette.web.models import ListenerWithSummary

LOGGER = getLogger(__name__)

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
    try:
        if not app_key:
            summaries = await telemetry.get_all_listeners_summary(since=since, source_tier=source_tier)
        else:
            summaries = await telemetry.get_listener_summary(
                app_key=app_key, instance_index=instance_index, since=since, source_tier=source_tier
            )
    except DB_ERRORS:
        LOGGER.warning("Failed to fetch listener metrics", exc_info=True)
        response.status_code = 503
        return []
    live_counts = hassette.bus_service.live_execution_counts()
    return [to_listener_with_summary(ls, live_counts) for ls in summaries]
