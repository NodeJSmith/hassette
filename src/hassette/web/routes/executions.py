"""Execution detail endpoint: one execution's record, API writes and logs."""

import time
from logging import getLogger
from typing import TYPE_CHECKING, Annotated

import uuid_utils
from fastapi import APIRouter, Query
from hassette_wire import ExecutionDetailResponse, LogEntry, ProblemCode

from hassette.const.misc import SECONDS_PER_DAY
from hassette.exceptions import TelemetryUnavailableError
from hassette.web.dependencies import AuthorQuery, HassetteDep, TelemetryDep
from hassette.web.errors import WebApiError, problem_responses

if TYPE_CHECKING:
    from hassette.core.telemetry.query_service import TelemetryQueryService

router = APIRouter(prefix="/executions", tags=["executions"])

LOGGER = getLogger(__name__)

EXECUTION_LOGS_DEFAULT_LIMIT = 500
"""Default number of log records, and separately of API writes, `/executions/{execution_id}` returns without `limit`."""

EXECUTION_LOGS_LIMIT_CAP = 5000
"""Upper bound a client may request via `/executions/{execution_id}`'s `limit` query parameter (each list)."""


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


async def check_retention_expired_uuid4(telemetry: "TelemetryQueryService", execution_id: str, cutoff: float) -> bool:
    """Fall back to DB query for non-UUIDv7 execution IDs (historical UUIDv4 IDs).

    Optional enrichment: the records are already in hand, so a telemetry failure here degrades
    to "not expired" instead of failing the request.
    """
    try:
        return await telemetry.check_execution_predates_retention_cutoff(execution_id, cutoff)
    except TelemetryUnavailableError:
        LOGGER.warning("Failed to check retention for %s — assuming not expired", execution_id, exc_info=True)
        return False


@router.get(
    "/{execution_id}",
    response_model=ExecutionDetailResponse,
    responses=problem_responses(ProblemCode.TELEMETRY_UNAVAILABLE),
)
async def get_execution_detail(
    execution_id: str,
    hassette: HassetteDep,
    telemetry: TelemetryDep,
    limit: Annotated[int, Query(ge=1, le=EXECUTION_LOGS_LIMIT_CAP)] = EXECUTION_LOGS_DEFAULT_LIMIT,
    author: AuthorQuery = None,
) -> ExecutionDetailResponse:
    """Return one execution's record, the API writes it made, and its log records.

    ``limit`` caps the writes and the logs separately. The record is written in batches, so it can
    lag the logs by a few seconds: ``execution`` is null until it lands (or once retention removed it).

    For UUIDv7 execution IDs, the embedded timestamp decides ``retention_expired`` without a
    database lookup. For historical UUIDv4 IDs, the database is queried.

    Returns 422 if the execution_id is not a valid UUID.
    """
    try:
        uuid_utils.UUID(execution_id)
    except ValueError as exc:
        raise WebApiError(
            ProblemCode.VALIDATION_FAILED, f"Invalid execution_id: {execution_id!r} is not a valid UUID"
        ) from exc

    execution = await telemetry.get_execution_by_id(execution_id)
    api_writes, api_writes_truncated = await telemetry.get_api_writes_by_execution(execution_id, limit=limit)
    records, logs_truncated = await telemetry.get_log_records_by_execution(execution_id, limit=limit, author=author)

    retention_expired = False
    if not records:
        cutoff = time.time() - hassette.config.logging.log_retention_days * SECONDS_PER_DAY
        ts_s = extract_uuidv7_timestamp_s(execution_id)
        if ts_s is not None:
            retention_expired = ts_s < cutoff
        else:
            retention_expired = await check_retention_expired_uuid4(telemetry, execution_id, cutoff)

    return ExecutionDetailResponse(
        execution=execution,
        api_writes=api_writes,
        api_writes_truncated=api_writes_truncated,
        logs=[LogEntry.model_validate(r) for r in records],
        logs_truncated=logs_truncated,
        retention_expired=retention_expired,
    )
