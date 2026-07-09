"""Log query endpoints."""

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response

from hassette.web.dependencies import VALID_LOG_LEVEL_NAMES, VALID_SOURCE_TIERS, TelemetryDep, db_degrades_to
from hassette.web.models import LogEntryResponse, LogLevelRequest, LogLevelResponse

router = APIRouter(tags=["logs"])


@router.get("/logs/recent", response_model=list[LogEntryResponse])
async def get_logs(
    telemetry: TelemetryDep,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=2000)] = 100,
    app_key: Annotated[str | None, Query()] = None,
    level: Annotated[str | None, Query()] = None,
    since: Annotated[float | None, Query()] = None,
    execution_id: Annotated[str | None, Query()] = None,
    source_tier: Annotated[str | None, Query()] = None,
) -> list[LogEntryResponse]:
    """Return recent log records from the database with optional filtering."""
    if level is not None:
        level = level.upper()
        if level not in VALID_LOG_LEVEL_NAMES:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid level {level!r}. Must be one of: {', '.join(sorted(VALID_LOG_LEVEL_NAMES))}",
            )
    if source_tier is not None:
        source_tier = source_tier.lower()
    if source_tier is not None and source_tier not in VALID_SOURCE_TIERS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid source_tier {source_tier!r}. Must be one of: {', '.join(sorted(VALID_SOURCE_TIERS))}",
        )
    records: list[LogEntryResponse] = []
    with db_degrades_to(response):
        raw = await telemetry.get_log_records(
            limit=limit,
            since=since,
            app_key=app_key,
            level=level,
            execution_id=execution_id,
            source_tier=source_tier,
        )
        records = [LogEntryResponse.model_validate(r) for r in raw]
    return records


@router.put("/logs/level", response_model=LogLevelResponse)
async def set_log_level(
    body: LogLevelRequest,
) -> LogLevelResponse:
    """Change a logger's effective level at runtime without restarting.

    The change takes effect immediately for both structlog and stdlib callers on that logger.
    """
    if not body.logger:
        raise HTTPException(status_code=422, detail="logger name must not be empty")
    level_upper = body.level.upper()
    if level_upper not in VALID_LOG_LEVEL_NAMES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid log level {body.level!r}. Must be one of: {', '.join(sorted(VALID_LOG_LEVEL_NAMES))}",
        )
    target_logger = logging.getLogger(body.logger)
    target_logger.setLevel(level_upper)
    effective = logging.getLevelName(target_logger.getEffectiveLevel())
    return LogLevelResponse(logger=body.logger, effective_level=str(effective))
