"""Log query endpoints."""

import logging
from logging import getLogger
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response

from hassette.web.auth.trusted_proxies import peer_address_or_unknown
from hassette.web.dependencies import (
    VALID_LOG_LEVEL_NAMES,
    VALID_SOURCE_TIERS,
    LimitQuery,
    TelemetryDep,
    db_degrades_to,
)
from hassette.web.models import LogEntryResponse, LogLevelRequest, LogLevelResponse

LOGGER = getLogger(__name__)

router = APIRouter(tags=["logs"])


def validate_log_level(level: str | None) -> str | None:
    """Uppercase and validate an optional ``level`` query param; raises 422 if invalid."""
    if level is None:
        return None
    level = level.upper()
    if level not in VALID_LOG_LEVEL_NAMES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid level {level!r}. Must be one of: {', '.join(sorted(VALID_LOG_LEVEL_NAMES))}",
        )
    return level


def validate_source_tier(source_tier: str | None) -> str | None:
    """Lowercase and validate an optional ``source_tier`` query param; raises 422 if invalid."""
    if source_tier is None:
        return None
    source_tier = source_tier.lower()
    if source_tier not in VALID_SOURCE_TIERS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid source_tier {source_tier!r}. Must be one of: {', '.join(sorted(VALID_SOURCE_TIERS))}",
        )
    return source_tier


@router.get("/logs/recent", response_model=list[LogEntryResponse])
async def get_logs(
    telemetry: TelemetryDep,
    response: Response,
    # Intentionally higher than the shared `LimitQuery` cap (500): this is the recency-first
    # dashboard view, which legitimately wants a bigger page than the cursor catch-up endpoint
    # below. Not drift — see `get_logs_since` for the cursor-based sibling using `LimitQuery`.
    limit: Annotated[int, Query(ge=1, le=2000)] = 100,
    app_key: Annotated[str | None, Query()] = None,
    level: Annotated[str | None, Query()] = None,
    since: Annotated[float | None, Query()] = None,
    execution_id: Annotated[str | None, Query()] = None,
    source_tier: Annotated[str | None, Query()] = None,
) -> list[LogEntryResponse]:
    """Return recent log records from the database with optional filtering."""
    level = validate_log_level(level)
    source_tier = validate_source_tier(source_tier)
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


@router.get("/logs/since/{since_id}", response_model=list[LogEntryResponse])
async def get_logs_since(
    since_id: Annotated[int, Path(ge=0)],
    telemetry: TelemetryDep,
    response: Response,
    limit: LimitQuery = 100,
    app_key: Annotated[str | None, Query()] = None,
    level: Annotated[str | None, Query()] = None,
    since: Annotated[float | None, Query()] = None,
    execution_id: Annotated[str | None, Query()] = None,
    source_tier: Annotated[str | None, Query()] = None,
) -> list[LogEntryResponse]:
    """Return log records with ``id > since_id``, ordered by ``id ASC``.

    Cursor-based catch-up endpoint — distinct from ``/logs/recent``, which orders by
    ``timestamp DESC, seq DESC`` for the recency-first dashboard view. A client that tracks
    the highest ``id`` it has seen can call this to fetch everything it missed (e.g. after a
    WebSocket reconnect) without gaps or duplicates.
    """
    level = validate_log_level(level)
    source_tier = validate_source_tier(source_tier)
    records: list[LogEntryResponse] = []
    with db_degrades_to(response):
        raw = await telemetry.get_log_records_since(
            since_id,
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
    request: Request,
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
    LOGGER.info(
        "Changed log level for %s to %s (source=%s)",
        body.logger,
        effective,
        peer_address_or_unknown(request),
    )
    return LogLevelResponse(logger=body.logger, effective_level=str(effective))
