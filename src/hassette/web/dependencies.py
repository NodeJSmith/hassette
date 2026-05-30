"""FastAPI dependency injection helpers for the Hassette Web API."""

import sqlite3
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Query, Request

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

DB_ERRORS: tuple[type[Exception], ...] = (sqlite3.Error, OSError, ValueError, TimeoutError)
"""Database error types to catch in web endpoints.

Includes ``ValueError`` because aiosqlite raises it for closed-connection
errors during shutdown and ``TimeoutError`` for queries exceeding the
configured read timeout.  All types are suppressed uniformly — a degraded
response is always preferable to an unhandled 500."""

SOURCE_TIER_PARAM = Query(
    default="app",
    description="Filter by source tier. 'app' excludes framework internals. "
    "'framework' returns only internal actors. 'all' returns everything.",
)
