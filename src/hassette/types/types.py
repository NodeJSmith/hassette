from collections.abc import Awaitable, Callable, Coroutine, Sequence
from dataclasses import dataclass
from datetime import time
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, Required, TypeAlias, TypeVar, runtime_checkable

from typing_extensions import TypeAliasType, TypedDict
from whenever import Time, TimeDelta, ZonedDateTime

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Generator

    from hassette.app.app_config import AppConfig
    from hassette.bus.error_context import BusErrorContext
    from hassette.const.misc import FalseySentinel
    from hassette.events import HassStateDict
    from hassette.events.base import Event, EventPayload
    from hassette.models.states.base import BaseState
    from hassette.scheduler.classes import ScheduledJob
    from hassette.scheduler.error_context import SchedulerErrorContext
    from hassette.task_bucket import TaskBucket


CliFormatStyle = Literal["duration_ms", "duration_s", "uptime", "relative_time", "services"]


LOG_LEVEL_TYPE = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
"""Log levels for configuring logging."""

FRAMEWORK_APP_KEY = "__hassette__"
"""Reserved app_key for framework-internal listeners and jobs.

Referenced in SQL constraints and in Python guards throughout the codebase.
All non-SQL usages should reference this constant or use ``is_framework_key()``."""

FRAMEWORK_APP_KEY_PREFIX = "__hassette__."
"""Prefix for component-specific framework keys (e.g. ``'__hassette__.service_watcher'``).

The trailing dot distinguishes the prefix from the bare sentinel so that
``'__hassette__other'`` is never mistakenly treated as a framework key.
Use ``is_framework_key()`` rather than comparing against this constant directly."""


@dataclass(frozen=True)
class CliFormat:
    """Annotated metadata marker declaring how a field renders in CLI human mode.

    Attach to model fields via ``Annotated[float, CliFormat("duration_ms")]``.
    The render layer introspects ``model_fields[name].metadata`` and dispatches
    to the matching formatter. JSON serialization is unaffected.
    """

    style: CliFormatStyle


SourceTier = Literal["app", "framework"]
"""Identifies whether a telemetry record originates from a user app or the framework itself."""

IfExistsPolicy = Literal["error", "skip", "replace"]
"""Collision policy for listener/job registration when a matching name already exists."""

BlockingAttributionReason = Literal["attributed", "framework", "displaced"]
"""Why a blocking event's ``app_key`` is what it is. All non-``"attributed"`` reasons have a NULL
``app_key``. ``"attributed"`` — the named app's task was the one frozen on / calling from the loop.
``"framework"`` — no app execution was responsible: Tier 2 had no marker bound (a genuine
framework/library call), or Tier 1 found the loop running its own machinery with no task in flight
(e.g. idle in ``select()``). ``"displaced"`` — an execution was bound but a *different* task was
frozen/calling, so the app_key was withheld rather than blaming the most-recently-bound app."""


class ExecutionStatus(StrEnum):
    """Status values for handler invocations and job executions.

    Covers all values allowed by the CHECK constraints in migrations 001 and 005.
    Pydantic v2 coerces plain strings to enum members on construction and
    serialises back to plain strings in JSON responses.
    """

    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    SKIPPED = "skipped"


QuerySourceTier = Literal["app", "framework", "all"]
"""Valid source_tier values for query-side filtering. 'all' disables the filter."""


def is_framework_key(app_key: str | None) -> bool:
    """Return True if *app_key* is a framework-reserved key.

    Matches both the legacy bare key ``'__hassette__'`` and any key with the
    component prefix ``'__hassette__.'``.

    Args:
        app_key: The app key to test. ``None`` returns ``False``.
    """
    if app_key is None:
        return False
    return app_key == FRAMEWORK_APP_KEY or app_key.startswith(FRAMEWORK_APP_KEY_PREFIX)


def framework_display_name(app_key: str) -> str:
    """Return a human-readable display name for a framework app key.

    For prefixed keys (e.g. ``'__hassette__.service_watcher'``) returns the
    component slug (``'service_watcher'``).  For the bare legacy key
    ``'__hassette__'`` returns ``'framework'``.

    Args:
        app_key: A framework app key.  Behaviour is undefined for non-framework keys.
    """
    if app_key.startswith(FRAMEWORK_APP_KEY_PREFIX):
        return app_key.removeprefix(FRAMEWORK_APP_KEY_PREFIX)
    return "framework"


CoroT = TypeVar("CoroT")
CoroLikeT = Coroutine[Any, Any, CoroT]
"""A coroutine returning a value of type CoroT."""


EventT = TypeVar("EventT", bound="Event[Any]", contravariant=True)
"""Represents an event type."""

PayloadT = TypeVar("PayloadT", bound="EventPayload[Any]", covariant=True)
"""Represents the payload type of an event."""

StateT = TypeVar("StateT", bound="BaseState", covariant=True)
"""Represents a specific state type, e.g., LightState, CoverState, etc."""

StateValueT = TypeVar("StateValueT", covariant=True)
"""Represents the type of the state attribute in a State model, e.g. bool for BinarySensorState."""

AppConfigT = TypeVar("AppConfigT", bound="AppConfig")
"""Type variable for app configuration classes."""


V = TypeVar("V")  # value type from the accessor
V_contra = TypeVar("V_contra", contravariant=True)


class Predicate(Protocol[EventT]):
    """Protocol for defining predicates that evaluate events."""

    def __call__(self, value: EventT, /) -> bool: ...


WhereClause: TypeAlias = "Predicate | Sequence[Predicate] | None"
"""Type alias for the ``where=`` parameter on bus/scheduler subscription methods."""


SchedulerPredicate = Callable[..., bool]
"""Synchronous callable used as a scheduler ``where=`` gate.

Dispatch arity is determined by the shared DI layer (``hassette.di``): a parameter
annotated as ``ScheduledJob`` receives the job instance via kwargs; unannotated
predicates (including lambdas) are called with zero arguments. Async callables raise
``TypeError`` at registration time."""


class Condition(Protocol[V_contra]):
    """Alias for a condition callable that takes a value or FalseySentinel and returns a bool."""

    def __call__(self, value: V_contra, /) -> bool: ...


class ComparisonCondition(Protocol[V_contra]):
    """Protocol for a comparison condition callable that takes two values and returns a bool."""

    def __call__(self, old_value: V_contra, new_value: V_contra, /) -> bool: ...


@runtime_checkable
class TriggerProtocol(Protocol):
    """Protocol for defining triggers.

    Six methods make up the contract:
    - first_run_time: returns the first scheduled run time given the current time
    - next_run_time: returns the next run time after a previous run, or None for one-shot triggers
    - trigger_label: short stable label for telemetry / UI display
    - trigger_detail: optional human-readable detail string
    - trigger_db_type: canonical type string for database storage
    - trigger_id: stable string identifier used for deduplication
    """

    def first_run_time(self, current_time: ZonedDateTime) -> ZonedDateTime:
        """Return the first scheduled run time at or after current_time."""
        ...

    def next_run_time(self, previous_run: ZonedDateTime, current_time: ZonedDateTime) -> ZonedDateTime | None:
        """Return the next run time after previous_run, or None for one-shot triggers."""
        ...

    def trigger_label(self) -> str:
        """Human-readable display label for the UI.

        Custom triggers (those returning ``"custom"`` from ``trigger_db_type()``)
        MUST NOT return one of the built-in reserved names (``"after"``,
        ``"once"``, ``"every"``, ``"daily"``, ``"cron"``) from this method.
        Doing so creates misleading telemetry and UI rows where the
        ``trigger_type`` column is ``"custom"`` but the label implies a
        built-in trigger kind.
        """
        ...

    def trigger_detail(self) -> str | None:
        """Optional human-readable detail string."""
        ...

    def trigger_db_type(self) -> Literal["interval", "cron", "once", "after", "custom"]:
        """Canonical type string for database storage."""
        ...

    def trigger_id(self) -> str:
        """Stable string identifier used for deduplication."""
        ...


class SchedulerServiceProtocol(Protocol):
    """Protocol for the scheduler-service surface consumed by Scheduler.

    Describes the surface Scheduler calls on its scheduler_service: the
    ``task_bucket`` attribute plus six async/sync methods. SchedulerService
    satisfies this protocol structurally — no changes to the concrete class
    are required.
    """

    task_bucket: "TaskBucket"

    async def add_job(self, job: "ScheduledJob") -> None: ...

    def dequeue_job(self, job: "ScheduledJob") -> bool: ...

    def register_removal_callback(self, owner_id: str, callback: "Callable[[ScheduledJob], None]") -> None: ...

    def deregister_removal_callback(self, owner_id: str) -> None: ...

    async def mark_job_cancelled(self, db_id: int) -> None: ...

    def remove_jobs_by_owner(self, owner: str) -> "asyncio.Task[None]": ...


class StateReader(Protocol):
    """Read-only protocol for the state-proxy surface consumed by StateManager and DomainStates.

    Describes the four members state-manager consumers call on the state proxy.
    StateProxy satisfies this protocol structurally — no changes to the
    concrete class are required.
    """

    def get_state(self, entity_id: str) -> "HassStateDict | None": ...

    def num_domain_states(self, domain: str) -> int: ...

    def yield_domain_states(self, domain: str) -> "Generator[tuple[str, HassStateDict], Any, None]": ...

    def __contains__(self, entity_id: str) -> bool: ...


class SyncHandler(Protocol):
    """Protocol for sync handlers."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...


class AsyncHandlerType(Protocol):
    """Protocol for async handlers."""

    def __call__(self, *args: Any, **kwargs: Any) -> Awaitable[None]: ...


# Type aliases for any valid handler
HandlerType = SyncHandler | AsyncHandlerType
"""Type representing all valid handler types (sync or async)."""

ChangeType = TypeAliasType(
    "ChangeType",
    "None | FalseySentinel | V | Condition[V | FalseySentinel] | ComparisonCondition[V | FalseySentinel]",
    type_params=(V,),
)
"""Type representing a value that can be used to specify changes in predicates."""

JobCallable: TypeAlias = Callable[..., Awaitable[None]] | Callable[..., Any]
"""Type representing a callable that can be scheduled as a job."""

ScheduleStartType: TypeAlias = ZonedDateTime | Time | time | TimeDelta | int | float | None
"""Type representing a value that can be used to specify a start time."""


BusErrorHandlerType: TypeAlias = Callable[["BusErrorContext"], Awaitable[None]] | Callable[["BusErrorContext"], None]
"""Type alias for bus error handler callables.

A bus error handler is either an async callable or a sync callable that accepts a
:class:`~hassette.bus.error_context.BusErrorContext` and returns ``None``.
"""

SchedulerErrorHandlerType: TypeAlias = (
    Callable[["SchedulerErrorContext"], Awaitable[None]] | Callable[["SchedulerErrorContext"], None]
)
"""Type alias for scheduler error handler callables.

A scheduler error handler is either an async callable or a sync callable that accepts a
:class:`~hassette.scheduler.error_context.SchedulerErrorContext` and returns ``None``.
"""


class RawAppDict(TypedDict, total=False):
    """Structure for raw app configuration before processing.

    Not all fields are required at this stage, as we will enrich and validate them later.
    """

    filename: Required[str]
    class_name: Required[str]
    app_dir: Path | str
    enabled: bool
    autostart: bool
    config: dict[str, Any] | list[dict[str, Any]]
    auto_loaded: bool


class AppDict(TypedDict, total=False):
    """Structure for processed app configuration."""

    app_key: Required[str]
    filename: Required[str]
    class_name: Required[str]
    app_dir: Required[Path]
    enabled: bool
    autostart: bool
    config: list[dict[str, Any]]
    auto_loaded: bool
    full_path: Required[Path]
