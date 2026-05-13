"""Log query endpoints."""

import logging
import time
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, HTTPException, Path, Query

from hassette.core import telemetry_repository as _repo
from hassette.web.dependencies import HassetteDep
from hassette.web.models import LogEntryResponse, LogLevelRequest, LogLevelResponse, LogsByExecutionResponse
from hassette.web.routes.telemetry import DB_ERRORS

if TYPE_CHECKING:
    from hassette import Hassette

router = APIRouter(tags=["logs"])

LOGGER = logging.getLogger(__name__)

_VALID_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
_VALID_SOURCE_TIERS = frozenset({"app", "framework"})
_SECONDS_PER_DAY = 86400


@router.get("/logs/recent", response_model=list[LogEntryResponse])
async def get_logs(
    hassette: HassetteDep,
    limit: Annotated[int, Query(ge=1, le=2000)] = 100,
    app_key: Annotated[str | None, Query()] = None,
    level: Annotated[str | None, Query()] = None,
    since: Annotated[float | None, Query()] = None,
    execution_id: Annotated[str | None, Query()] = None,
    source_tier: Annotated[str | None, Query()] = None,
) -> list[dict]:
    """Return recent log records from the database with optional filtering."""
    if level is not None:
        level = level.upper()
        if level not in _VALID_LEVELS:
            raise HTTPException(
                status_code=422, detail=f"Invalid level {level!r}. Must be one of: {', '.join(sorted(_VALID_LEVELS))}"
            )
    if source_tier is not None and source_tier not in _VALID_SOURCE_TIERS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid source_tier {source_tier!r}. Must be one of: {', '.join(sorted(_VALID_SOURCE_TIERS))}",
        )
    try:
        records: list[dict] = await _repo.get_log_records(
            hassette.database_service.read_db,
            limit=limit,
            since=since,
            app_key=app_key,
            level=level,
            execution_id=execution_id,
            source_tier=source_tier,
        )
        return records
    except DB_ERRORS:
        LOGGER.warning("Failed to fetch recent log records", exc_info=True)
        return []


@router.get("/logs/by-execution/{execution_id}", response_model=LogsByExecutionResponse)
async def get_logs_by_execution(
    hassette: HassetteDep,
    execution_id: Annotated[str, Path()],
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
) -> LogsByExecutionResponse:
    """Return all log records for a single execution, with retention-expired detection."""
    try:
        records, truncated = await _repo.get_log_records_by_execution(
            hassette.database_service.read_db,
            execution_id,
            limit=limit,
        )
    except DB_ERRORS:
        LOGGER.warning("Failed to fetch log records for execution %s", execution_id, exc_info=True)
        return LogsByExecutionResponse(records=[], truncated=False, retention_expired=False)

    retention_expired = False
    if not records:
        retention_expired = await _check_retention_expired(hassette, execution_id)

    log_entries = [LogEntryResponse.model_validate(r) for r in records]
    return LogsByExecutionResponse(records=log_entries, truncated=truncated, retention_expired=retention_expired)


async def _check_retention_expired(hassette: "Hassette", execution_id: str) -> bool:
    """Return True if logs were deleted by retention policy.

    Checks handler_invocations and job_executions for the execution_id. If the
    execution's timestamp is older than log_retention_days, its logs have been expired.
    """
    try:
        cutoff = time.time() - hassette.config.log_retention_days * _SECONDS_PER_DAY
        return await _repo.check_execution_predates_retention_cutoff(
            hassette.database_service.read_db, execution_id, cutoff
        )
    except DB_ERRORS:
        return False


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
