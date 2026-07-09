"""FastAPI dependency injection helpers for the Hassette Web API."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from logging import getLogger
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Query, Request
from starlette.responses import Response

from hassette.exceptions import TelemetryUnavailableError

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.api import Api
    from hassette.core.runtime_query_service import RuntimeQueryService
    from hassette.core.scheduler_service import SchedulerService
    from hassette.core.telemetry.query_service import TelemetryQueryService


def get_hassette(request: Request) -> "Hassette":
    return request.app.state.hassette


def get_runtime(request: Request) -> "RuntimeQueryService":
    return request.app.state.hassette.runtime_query_service


def get_telemetry(request: Request) -> "TelemetryQueryService":
    return request.app.state.hassette.telemetry_query_service


def get_scheduler(request: Request) -> "SchedulerService":
    return request.app.state.hassette.scheduler_service


def get_api(request: Request) -> "Api":
    return request.app.state.hassette.api


# Shared dependency type aliases — import these instead of re-defining locally.
HassetteDep = Annotated["Hassette", Depends(get_hassette)]
RuntimeDep = Annotated["RuntimeQueryService", Depends(get_runtime)]
TelemetryDep = Annotated["TelemetryQueryService", Depends(get_telemetry)]
SchedulerDep = Annotated["SchedulerService", Depends(get_scheduler)]
ApiDep = Annotated["Api", Depends(get_api)]

LOGGER = getLogger(__name__)


@contextmanager
def db_degrades_to(response: Response) -> Iterator[None]:
    """Context manager that degrades a response to 503 on telemetry unavailability.

    Catches ``TelemetryUnavailableError``, logs a warning with full traceback, and sets
    ``response.status_code = 503``.  All other exceptions propagate unchanged.
    Callers pre-initialize their result to the failure default and return at the
    tail so the default is used when the CM suppresses the error.
    """
    try:
        yield
    except TelemetryUnavailableError:
        LOGGER.warning("DB query failed; degrading to 503", exc_info=True)
        response.status_code = 503


LOG_LEVELS: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

VALID_LOG_LEVEL_NAMES: frozenset[str] = frozenset(LOG_LEVELS)

SOURCE_TIER_PARAM = Query(
    default="app",
    description="Filter by source tier. 'app' excludes framework internals. "
    "'framework' returns only internal actors. 'all' returns everything.",
)
