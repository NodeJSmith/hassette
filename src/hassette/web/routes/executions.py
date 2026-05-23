"""Execution log endpoint."""

import logging
import time
from typing import TYPE_CHECKING, Annotated

import uuid_utils
from fastapi import APIRouter, HTTPException, Query, Response

from hassette.const.misc import SECONDS_PER_DAY
from hassette.core import telemetry_repository as _repo
from hassette.web.dependencies import HassetteDep
from hassette.web.models import LogEntryResponse, LogsByExecutionResponse
from hassette.web.routes.telemetry import DB_ERRORS

if TYPE_CHECKING:
    from hassette import Hassette

router = APIRouter(prefix="/executions", tags=["executions"])

LOGGER = logging.getLogger(__name__)


def extract_uuidv7_timestamp_s(execution_id: str) -> float | None:
    """Return the Unix timestamp (seconds) embedded in a UUIDv7 string, or None if not v7.

    UUIDv7 embeds a 48-bit Unix millisecond timestamp in the first 48 bits. Falls back
    to None for non-UUIDv7 IDs (e.g. historical UUIDv4 IDs).
    """
    try:
        parsed = uuid_utils.UUID(execution_id)
    except (ValueError, AttributeError):
        return None
    if parsed.version != 7:
        return None
    return parsed.timestamp / 1000.0


async def check_retention_expired_uuid4(hassette: "Hassette", execution_id: str) -> bool:
    """Fall back to DB query for non-UUIDv7 execution IDs (historical UUIDv4 IDs)."""
    try:
        cutoff = time.time() - hassette.config.logging.log_retention_days * SECONDS_PER_DAY
        return await _repo.check_execution_predates_retention_cutoff(
            hassette.database_service.read_db, execution_id, cutoff
        )
    except DB_ERRORS:
        return False


@router.get("/{execution_id}", response_model=LogsByExecutionResponse)
async def get_execution_logs(
    execution_id: str,
    hassette: HassetteDep,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
) -> LogsByExecutionResponse:
    """Return all log records for a single execution, with retention-expired detection.

    For UUIDv7 execution IDs, the embedded timestamp is extracted directly without a
    database lookup. For historical UUIDv4 IDs, the database is queried to determine
    whether retention has expired.

    Returns 422 if the execution_id is not a valid UUID. Returns an empty record list
    with ``retention_expired=True`` if logs have been purged by retention policy.
    """
    try:
        uuid_utils.UUID(execution_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=f"Invalid execution_id: {execution_id!r} is not a valid UUID"
        ) from exc

    try:
        records, truncated = await _repo.get_log_records_by_execution(
            hassette.database_service.read_db,
            execution_id,
            limit=limit,
        )
    except DB_ERRORS:
        LOGGER.warning("Failed to fetch log records for execution %s", execution_id, exc_info=True)
        response.status_code = 503
        return LogsByExecutionResponse(records=[], truncated=False, retention_expired=False)

    retention_expired = False
    if not records:
        ts_s = extract_uuidv7_timestamp_s(execution_id)
        if ts_s is not None:
            # UUIDv7: extract embedded timestamp — no DB lookup needed
            cutoff = time.time() - hassette.config.logging.log_retention_days * SECONDS_PER_DAY
            retention_expired = ts_s < cutoff
        else:
            # UUIDv4 or other version: fall back to DB query
            retention_expired = await check_retention_expired_uuid4(hassette, execution_id)

    log_entries = [LogEntryResponse.model_validate(r) for r in records]
    return LogsByExecutionResponse(records=log_entries, truncated=truncated, retention_expired=retention_expired)
