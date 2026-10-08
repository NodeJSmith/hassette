"""Log query endpoints."""

import logging
from collections.abc import Callable
from logging import getLogger
from typing import Annotated

from fastapi import APIRouter, Query, Request
from hassette_wire import LogEntry, LogLevelRequest, LogLevelResponse, ProblemCode

from hassette.web.auth.trusted_proxies import peer_address_or_unknown
from hassette.web.dependencies import (
    VALID_LOG_LEVEL_NAMES,
    SinceQuery,
    SourceTierQuery,
    TelemetryDep,
    is_log_level,
)
from hassette.web.errors import WebApiError, problem_responses

LOGGER = getLogger(__name__)

RECENT_LOGS_DEFAULT_LIMIT = 100
"""Default number of log records `/logs/recent` returns when the client omits `limit`."""

RECENT_LOGS_LIMIT_CAP = 2000
"""Upper bound a client may request via `/logs/recent`'s `limit` query parameter."""

router = APIRouter(tags=["logs"])


def _validate_choice(
    value: str | None, valid: frozenset[str], param_name: str, transform: Callable[[str], str]
) -> str | None:
    """Normalize and validate an optional query param against a fixed set of choices; raises 422 if invalid."""
    if value is None:
        return None
    value = transform(value)
    if value not in valid:
        raise WebApiError(
            ProblemCode.VALIDATION_FAILED,
            f"Invalid {param_name} {value!r}. Must be one of: {', '.join(sorted(valid))}",
        )
    return value


def validate_log_level(level: str | None) -> str | None:
    """Uppercase and validate an optional ``level`` query param; raises 422 if invalid."""
    return _validate_choice(level, VALID_LOG_LEVEL_NAMES, "level", str.upper)


@router.get(
    "/logs/recent",
    response_model=list[LogEntry],
    responses=problem_responses(ProblemCode.TELEMETRY_UNAVAILABLE),
)
async def get_logs(
    telemetry: TelemetryDep,
    limit: Annotated[int, Query(ge=1, le=RECENT_LOGS_LIMIT_CAP)] = RECENT_LOGS_DEFAULT_LIMIT,
    app_key: Annotated[str | None, Query()] = None,
    level: Annotated[str | None, Query()] = None,
    since: SinceQuery = None,
    execution_id: Annotated[str | None, Query()] = None,
    # Unlike the telemetry-metrics endpoints, which default to "app", this default deliberately
    # includes everything: the log viewer is a raw feed, not an app-author-facing metric.
    source_tier: SourceTierQuery = "all",
) -> list[LogEntry]:
    """Return recent log records from the database with optional filtering."""
    level = validate_log_level(level)
    raw = await telemetry.get_log_records(
        limit=limit,
        since=since,
        app_key=app_key,
        level=level,
        execution_id=execution_id,
        source_tier=source_tier,
    )
    return [LogEntry.model_validate(r) for r in raw]


@router.put("/logs/level", response_model=LogLevelResponse)
async def set_log_level(
    body: LogLevelRequest,
    request: Request,
) -> LogLevelResponse:
    """Change a logger's effective level at runtime without restarting.

    The change takes effect immediately for both structlog and stdlib callers on that logger.
    """
    if not body.logger:
        raise WebApiError(ProblemCode.VALIDATION_FAILED, "logger name must not be empty")
    level_upper = body.level.upper()
    if not is_log_level(level_upper):
        raise WebApiError(
            ProblemCode.VALIDATION_FAILED,
            f"Invalid log level {body.level!r}. Must be one of: {', '.join(sorted(VALID_LOG_LEVEL_NAMES))}",
        )
    target_logger = logging.getLogger(body.logger)
    target_logger.setLevel(level_upper)
    # Read the level back rather than echoing the request, so the response reports the logger's real state.
    # The raise guards an invariant, not an input: level_upper is one of the five standard names, so
    # the effective level can only differ if something replaces logging's level handling.
    effective = logging.getLevelName(target_logger.getEffectiveLevel())
    if not is_log_level(effective):
        raise RuntimeError(f"Logger {body.logger!r} reports non-standard effective level {effective!r}")
    LOGGER.info(
        "Changed log level for %s to %s (source=%s)",
        body.logger,
        effective,
        peer_address_or_unknown(request),
    )
    return LogLevelResponse(logger=body.logger, effective_level=effective)
