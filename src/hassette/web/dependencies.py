"""FastAPI dependency injection helpers for the Hassette Web API."""

from dataclasses import dataclass
from logging import CRITICAL, DEBUG, ERROR, INFO, WARNING
from typing import TYPE_CHECKING, Annotated, TypedDict, TypeGuard

from fastapi import Depends, Path, Query, Request
from hassette_wire import LogLevel, QuerySourceTier

from hassette.schemas.query_constants import MAX_QUERY_LIMIT

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.api import Api
    from hassette.core.runtime_query_service import RuntimeQueryService
    from hassette.core.scheduler_service import SchedulerService
    from hassette.core.telemetry.query_service import TelemetryQueryService


LOG_LEVELS: dict[LogLevel, int] = {
    "DEBUG": DEBUG,
    "INFO": INFO,
    "WARNING": WARNING,
    "ERROR": ERROR,
    "CRITICAL": CRITICAL,
}
VALID_LOG_LEVEL_NAMES: frozenset[str] = frozenset(LOG_LEVELS)
VALID_SOURCE_TIERS: frozenset[str] = frozenset({"app", "framework"})

# Shared query/path parameter annotations — annotate route parameters with these instead of
# repeating the `Query(...)`/`Path(...)` call in every signature.
AppKeyPath = Annotated[str, Path(description="Use `__hassette__` to query framework-internal actor telemetry.")]
InstanceIndexQuery = Annotated[
    int, Query(description="App instance index. Defaults to 0. Multi-instance apps have indices 0..N-1.")
]
# For routes that serve the multi-instance parent overview, where omitting the index means every instance.
OptionalInstanceIndexQuery = Annotated[
    int | None, Query(description="App instance index. Omit for every instance of the app.")
]
SinceQuery = Annotated[float | None, Query(allow_inf_nan=False)]
SourceTierQuery = Annotated[
    QuerySourceTier,
    Query(
        description="Filter by source tier. 'app' excludes framework internals. "
        "'framework' returns only internal actors. 'all' returns everything."
    ),
]
"""Source-tier filter for telemetry-metrics endpoints, which default to ``"app"``.

``GET /logs/recent`` deliberately defaults to both tiers instead — see ``routes/logs.py``.
"""
LimitQuery = Annotated[int, Query(ge=1, le=MAX_QUERY_LIMIT)]


def is_log_level(name: str) -> TypeGuard[LogLevel]:
    """Whether ``name`` is one of the five standard level names. Case-sensitive: upper-case input first."""
    return name in VALID_LOG_LEVEL_NAMES


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


def get_resolved_auth_token(request: Request) -> str | None:
    """Return the resolved web API credential from app state, or ``None`` if unset.

    Mirrors the guarded lookup used by ``DefaultDenyMiddleware`` and ``authorize_ws`` so an
    app built without an ``auth_token`` argument degrades to ``None`` rather than raising.
    """
    return getattr(request.app.state, "auth_token", None)


# Shared dependency type aliases — import these instead of re-defining locally.
HassetteDep = Annotated["Hassette", Depends(get_hassette)]
RuntimeDep = Annotated["RuntimeQueryService", Depends(get_runtime)]
TelemetryDep = Annotated["TelemetryQueryService", Depends(get_telemetry)]
SchedulerDep = Annotated["SchedulerService", Depends(get_scheduler)]
ApiDep = Annotated["Api", Depends(get_api)]
AuthDep = Annotated[str | None, Depends(get_resolved_auth_token)]


class TelemetryFilterKwargs(TypedDict):
    """Keyword arguments accepted by every per-app ``TelemetryQueryService`` filter method."""

    instance_index: int
    since: float | None
    source_tier: QuerySourceTier


@dataclass
class TelemetryFilters:
    """The instance/time/tier query parameters shared by the per-app telemetry routes.

    Declared once here and injected via ``TelemetryFiltersDep`` so a route signature names the
    filter set instead of restating all three parameters. FastAPI flattens a dependency's
    parameters into the operation, so the OpenAPI schema is the same as declaring them inline.
    """

    instance_index: InstanceIndexQuery = 0
    since: SinceQuery = None
    source_tier: SourceTierQuery = "app"

    @property
    def query_kwargs(self) -> TelemetryFilterKwargs:
        """Splat into a ``TelemetryQueryService`` method that accepts these three filters."""
        return {"instance_index": self.instance_index, "since": self.since, "source_tier": self.source_tier}


TelemetryFiltersDep = Annotated[TelemetryFilters, Depends()]
