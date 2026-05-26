"""Log query endpoints."""

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response

from hassette.web.dependencies import TelemetryDep
from hassette.web.models import LogEntryResponse, LogLevelRequest, LogLevelResponse
from hassette.web.routes.telemetry import DB_ERRORS

router = APIRouter(tags=["logs"])

LOGGER = logging.getLogger(__name__)

_VALID_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
_VALID_SOURCE_TIERS = frozenset({"app", "framework"})


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
        if level not in _VALID_LEVELS:
            raise HTTPException(
                status_code=422, detail=f"Invalid level {level!r}. Must be one of: {', '.join(sorted(_VALID_LEVELS))}"
            )
    if source_tier is not None:
        source_tier = source_tier.lower()
    if source_tier is not None and source_tier not in _VALID_SOURCE_TIERS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid source_tier {source_tier!r}. Must be one of: {', '.join(sorted(_VALID_SOURCE_TIERS))}",
        )
    try:
        records = await telemetry.get_log_records(
            limit=limit,
            since=since,
            app_key=app_key,
            level=level,
            execution_id=execution_id,
            source_tier=source_tier,
        )
        return [LogEntryResponse.model_validate(r) for r in records]
    except DB_ERRORS:
        LOGGER.warning("Failed to fetch recent log records", exc_info=True)
        response.status_code = 503
        return []


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
    if level_upper not in _VALID_LEVELS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid log level {body.level!r}. Must be one of: {', '.join(sorted(_VALID_LEVELS))}",
        )
    target_logger = logging.getLogger(body.logger)
    target_logger.setLevel(level_upper)
    effective = logging.getLevelName(target_logger.getEffectiveLevel())
    return LogLevelResponse(logger=body.logger, effective_level=str(effective))
