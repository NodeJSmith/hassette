import typing
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import time
from typing import Any, Protocol, TypeAlias, TypeVar, runtime_checkable

from typing_extensions import Sentinel, TypeAliasType
from whenever import Date, PlainDateTime, Time, TimeDelta, ZonedDateTime

if typing.TYPE_CHECKING:
    from .events import Event

EventT = TypeVar("EventT", bound="Event[Any]", contravariant=True)


@runtime_checkable
class Predicate(Protocol[EventT]):
    """Protocol for defining predicates that evaluate events."""

    def __call__(self, event: EventT) -> bool: ...


class Condition(Protocol):
    """Protocol for defining conditions on known types."""

    def __call__(self, value: "KnownType") -> bool: ...


class Handler(Protocol[EventT]):
    """Protocol for defining event handlers."""

    def __call__(self, event: EventT) -> Awaitable[None] | None: ...


class HandlerVariadic(Protocol[EventT]):
    def __call__(self, event: EventT, *args: object, **kwargs: Any) -> Awaitable[None] | None: ...


class AsyncHandler(Protocol[EventT]):
    """Protocol for defining asynchronous event handlers."""

    def __call__(self, event: EventT) -> Awaitable[None]: ...


class AsyncHandlerVariadic(Protocol[EventT]):
    def __call__(self, event: EventT, *args: object, **kwargs: Any) -> Awaitable[None]: ...


class TriggerProtocol(Protocol):
    """Protocol for defining triggers."""

    def next_run_time(self) -> ZonedDateTime:
        """Return the next run time of the trigger."""
        ...


AsyncHandlerType = TypeAliasType(
    "AsyncHandlerType", AsyncHandler[EventT] | AsyncHandlerVariadic[EventT], type_params=(EventT,)
)
"""Alias for all valid async handler types."""

HandlerType = TypeAliasType(
    "HandlerType",
    Handler[EventT] | HandlerVariadic[EventT] | AsyncHandler[EventT] | AsyncHandlerVariadic[EventT],
    type_params=(EventT,),
)
"""Alias for all valid handler types."""

_KnownType: TypeAlias = ZonedDateTime | PlainDateTime | Time | Date | None | float | int | bool | str

KnownType: TypeAlias = _KnownType | Sequence[_KnownType] | Mapping[str, _KnownType]
"""Alias for all known valid state types."""

ChangeType: TypeAlias = "None | Sentinel | KnownType | Condition"
"""Alias for types that can be used to specify state or attribute changes."""

JobCallable = Callable[..., Awaitable[None]] | Callable[..., Any]
"""Alias for a callable that can be scheduled as a job."""

ScheduleStartType = ZonedDateTime | Time | time | tuple[int, int] | TimeDelta | int | float | None
"""Type for specifying start times."""
