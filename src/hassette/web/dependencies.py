"""FastAPI dependency injection helpers for the Hassette Web API."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, TypedDict, TypeGuard

from fastapi import Depends, Path, Query, Request
from hassette_wire import LogLevel, QueryAuthor, QuerySourceTier

from hassette.schemas.query_constants import MAX_QUERY_LIMIT
from hassette.types.types import APP_SOURCE_TIER, LOG_LEVELS, is_framework_key

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.api import Api
    from hassette.core.runtime_query_service import RuntimeQueryService
    from hassette.core.scheduler_service import SchedulerService
    from hassette.core.telemetry.query_service import TelemetryQueryService


VALID_LOG_LEVEL_NAMES: frozenset[str] = frozenset(LOG_LEVELS)

DEFAULT_INSTANCE_INDEX = 0

# Shared query/path parameter annotations — annotate route parameters with these instead of
# repeating the `Query(...)`/`Path(...)` call in every signature.
AppKeyPath = Annotated[str, Path(description="Use `__hassette__` to query framework-internal actor telemetry.")]
"""App key path parameter; also accepts the framework-internal ``__hassette__`` actor."""
InstanceIndexQuery = Annotated[
    int,
    Query(
        description=f"App instance index. Defaults to {DEFAULT_INSTANCE_INDEX}. "
        "Multi-instance apps have indices 0..N-1."
    ),
]
"""Instance index for routes that view one instance; pair it with ``= DEFAULT_INSTANCE_INDEX``."""
OptionalInstanceIndexQuery = Annotated[
    int | None, Query(description="App instance index. Omit for every instance of the app.")
]
"""Instance index for routes that serve the multi-instance parent overview, where omitting it means every instance."""
SinceQuery = Annotated[float | None, Query(allow_inf_nan=False)]
"""Lower time bound (epoch seconds); rejects NaN and infinity."""
SourceTierQuery = Annotated[
    QuerySourceTier,
    Query(
        description="Filter by source tier. 'app' excludes framework internals. "
        "'framework' returns only internal actors. 'all' returns everything."
    ),
]
"""Source-tier filter shared by the telemetry routes; each route chooses its own default (usually ``"app"``).

Log routes filter by ``AuthorQuery`` instead.
"""
AuthorQuery = Annotated[
    QueryAuthor | None,
    Query(
        description="Filter log lines by who wrote them. Omit for the default view: app-authored lines plus "
        "framework lines at ERROR and above. 'all' returns every line; 'app' or 'framework' returns only "
        "that author's lines."
    ),
]
"""Author filter shared by the log routes; ``None`` applies the default view (see ``log_author_clause``)."""
LimitQuery = Annotated[int, Query(ge=1, le=MAX_QUERY_LIMIT)]
"""Row limit, capped at ``MAX_QUERY_LIMIT``."""


def is_log_level(name: str) -> TypeGuard[LogLevel]:
    """Whether ``name`` is one of the five standard level names. Case-sensitive: upper-case input first."""
    return name in VALID_LOG_LEVEL_NAMES


def get_hassette(request: Request) -> "Hassette":
    """Return the Hassette instance attached to the app at construction."""
    return request.app.state.hassette


def get_runtime(request: Request) -> "RuntimeQueryService":
    """Return the service that answers live runtime queries (status, apps, WebSocket clients)."""
    return request.app.state.hassette.runtime_query_service


def get_telemetry(request: Request) -> "TelemetryQueryService":
    """Return the service that queries the persisted telemetry database."""
    return request.app.state.hassette.telemetry_query_service


def get_scheduler(request: Request) -> "SchedulerService":
    """Return the framework scheduler service, which owns every app's scheduled jobs."""
    return request.app.state.hassette.scheduler_service


def get_api(request: Request) -> "Api":
    """Return the framework-level Home Assistant API client."""
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


def instance_name_filter(hassette: "Hassette", app_key: str | None, index: int | None) -> str | None:
    """Translate a route's instance index to the name telemetry queries filter on; ``None`` means no filter.

    A framework key has exactly one instance, so its queries need no instance filter. An index with no
    configured name resolves to a display label that can't pass name validation, so it matches no stored row
    and the query answers empty rather than another instance's history.
    """
    if app_key is None or index is None or is_framework_key(app_key):
        return None
    return hassette.app_handler.registry.instance_name(app_key, index)


class TelemetryFilterKwargs(TypedDict):
    """Keyword arguments accepted by every per-app ``TelemetryQueryService`` filter method."""

    instance_name: str | None
    since: float | None
    source_tier: QuerySourceTier


@dataclass
class TelemetryFilters:
    """The instance/time/tier query parameters shared by the per-app telemetry routes.

    ``hassette`` is an injected dependency for resolving the index to its name, not a query parameter.

    Declared once here and injected via ``TelemetryFiltersDep`` so a route signature names the
    filter set instead of restating all three parameters. FastAPI flattens a dependency's
    parameters into the operation, so the OpenAPI schema is the same as declaring them inline.
    """

    hassette: HassetteDep
    instance_index: InstanceIndexQuery = DEFAULT_INSTANCE_INDEX
    since: SinceQuery = None
    source_tier: SourceTierQuery = APP_SOURCE_TIER

    def query_kwargs(self, app_key: str | None) -> TelemetryFilterKwargs:
        """Splat into a ``TelemetryQueryService`` method that accepts these three filters for ``app_key``."""
        return {
            "instance_name": instance_name_filter(self.hassette, app_key, self.instance_index),
            "since": self.since,
            "source_tier": self.source_tier,
        }


TelemetryFiltersDep = Annotated[TelemetryFilters, Depends()]
