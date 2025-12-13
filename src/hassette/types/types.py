from collections.abc import Awaitable, Callable
from datetime import time
from pathlib import Path
from typing import Any, Literal, Protocol, Required, TypeAlias, TypeVar

from typing_extensions import TypeAliasType, TypedDict
from whenever import Time, TimeDelta, ZonedDateTime

from hassette.const.misc import FalseySentinel
from hassette.events.base import EventT

LOG_LEVELS = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
"""Log levels for configuring logging."""


V = TypeVar("V")  # value type from the accessor
V_contra = TypeVar("V_contra", contravariant=True)


class Predicate(Protocol[EventT]):
    """Protocol for defining predicates that evaluate events."""

    def __call__(self, event: EventT) -> bool: ...


class Condition(Protocol[V_contra]):
    """Alias for a condition callable that takes a value or FalseySentinel and returns a bool."""

    def __call__(self, value: V_contra, /) -> bool: ...


class ComparisonCondition(Protocol[V_contra]):
    """Protocol for a comparison condition callable that takes two values and returns a bool."""

    def __call__(self, old_value: V_contra, new_value: V_contra, /) -> bool: ...


class TriggerProtocol(Protocol):
    """Protocol for defining triggers."""

    def next_run_time(self) -> ZonedDateTime:
        """Return the next run time of the trigger."""
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
    None | FalseySentinel | V | Condition[V | FalseySentinel] | ComparisonCondition[V | FalseySentinel],
    type_params=(V,),
)
"""Type representing a value that can be used to specify changes in predicates."""

JobCallable: TypeAlias = Callable[..., Awaitable[None]] | Callable[..., Any]
"""Type representing a callable that can be scheduled as a job."""

ScheduleStartType: TypeAlias = ZonedDateTime | Time | time | tuple[int, int] | TimeDelta | int | float | None
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
