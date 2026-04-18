from collections.abc import Awaitable, Callable, Coroutine
from datetime import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, Required, TypeAlias, TypeVar, runtime_checkable

from typing_extensions import TypeAliasType, TypedDict
from whenever import Time, TimeDelta, ZonedDateTime

if TYPE_CHECKING:
    from hassette.app.app_config import AppConfig
    from hassette.const.misc import FalseySentinel
    from hassette.events.base import Event, EventPayload
    from hassette.models.states.base import BaseState


LOG_LEVEL_TYPE = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
"""Log levels for configuring logging."""

SourceTier = Literal["app", "framework"]
"""Identifies whether a telemetry record originates from a user app or the framework itself."""

QuerySourceTier = Literal["app", "framework", "all"]
"""Valid source_tier values for query-side filtering. 'all' disables the filter."""

FRAMEWORK_APP_KEY = "__hassette__"
"""Reserved app_key for framework-internal listeners and jobs.

Referenced in SQL constraints and in Python guards throughout the codebase.
All non-SQL usages should reference this constant or use ``is_framework_key()``."""

FRAMEWORK_APP_KEY_PREFIX = "__hassette__."
"""Prefix for component-specific framework keys (e.g. ``'__hassette__.service_watcher'``).

The trailing dot distinguishes the prefix from the bare sentinel so that
``'__hassette__other'`` is never mistakenly treated as a framework key.
Use ``is_framework_key()`` rather than comparing against this constant directly."""


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
        """Short stable label for telemetry / UI display.

        Custom triggers (those returning ``"custom"`` from ``trigger_db_type()``)
        MUST NOT return one of the built-in reserved names (``"interval"``,
        ``"cron"``, ``"once"``, ``"after"``) from this method. Doing so creates
        misleading telemetry and UI rows where the ``trigger_type`` column is
        ``"custom"`` but the label implies a built-in trigger kind.
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


class RawAppDict(TypedDict, total=False):
    """Structure for raw app configuration before processing.

    Not all fields are required at this stage, as we will enrich and validate them later.
    """

    filename: Required[str]
    class_name: Required[str]
    app_dir: Path | str
    enabled: bool
    config: dict[str, Any] | list[dict[str, Any]]
    auto_loaded: bool


class AppDict(TypedDict, total=False):
    """Structure for processed app configuration."""

    app_key: Required[str]
    filename: Required[str]
    class_name: Required[str]
    app_dir: Required[Path]
    enabled: bool
    config: list[dict[str, Any]]
    auto_loaded: bool
    full_path: Required[Path]
