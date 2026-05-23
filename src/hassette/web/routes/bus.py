"""Bus listener metrics endpoints."""

from typing import Annotated

from fastapi import APIRouter, Query

from hassette.types.types import QuerySourceTier
from hassette.web.dependencies import SOURCE_TIER_PARAM, RuntimeDep, TelemetryDep
from hassette.web.mappers import to_listener_with_summary
from hassette.web.models import ListenerWithSummary
from hassette.web.utils import gather_all_listeners

router = APIRouter(tags=["bus"])


@router.get("/bus/listeners", response_model=list[ListenerWithSummary])
async def get_listener_metrics(
    runtime: RuntimeDep,
    telemetry: TelemetryDep,
    app_key: Annotated[str | None, Query()] = None,
    instance_index: Annotated[
        int,
        Query(description="App instance index. Defaults to 0. Multi-instance apps have indices 0..N-1."),
    ] = 0,
    since: float | None = Query(default=None),  # pyright: ignore[reportCallInDefaultInitializer]
    source_tier: QuerySourceTier | None = SOURCE_TIER_PARAM,
) -> list[ListenerWithSummary]:
    effective_tier = source_tier if source_tier is not None else "app"
    if not app_key:
        summaries = await gather_all_listeners(runtime, telemetry, since=since)
        if effective_tier != "all":
            summaries = [s for s in summaries if s.source_tier == effective_tier]
    else:
        summaries = await telemetry.get_listener_summary(
            app_key=app_key, instance_index=instance_index, since=since, source_tier=effective_tier
        )
    return [to_listener_with_summary(ls) for ls in summaries]
