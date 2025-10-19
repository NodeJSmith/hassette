import typing
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import time
from typing import Any, Protocol, TypeAlias, TypeVar

from typing_extensions import Sentinel, TypeAliasType
from whenever import Date, PlainDateTime, Time, TimeDelta, ZonedDateTime

if typing.TYPE_CHECKING:
    from .events import Event

EventT = TypeVar("EventT", bound="Event[Any]", contravariant=True)

V = TypeVar("V")  # value type from the accessor
V_contra = TypeVar("V_contra", contravariant=True)


class Predicate(Protocol[EventT]):
    """Protocol for defining predicates that evaluate events."""

    def __call__(self, event: EventT) -> bool: ...


class Condition(Protocol[V_contra]):
    """Alias for a condition callable that takes a value or Sentinel and returns a bool."""

    def __call__(self, value: V_contra, /) -> bool: ...


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

KnownTypeScalar: TypeAlias = ZonedDateTime | PlainDateTime | Time | Date | None | float | int | bool | str
"""Alias for all known valid scalar state types."""

KnownType: TypeAlias = KnownTypeScalar | Sequence[KnownTypeScalar] | Mapping[str, KnownTypeScalar]
"""Alias for all known valid state types."""

ChangeType = TypeAliasType("ChangeType", None | Sentinel | V | Condition[V | Sentinel], type_params=(V,))
"""Alias for types that can be used to specify changes in predicates."""

JobCallable: TypeAlias = Callable[..., Awaitable[None]] | Callable[..., Any]
"""Alias for a callable that can be scheduled as a job."""

ScheduleStartType: TypeAlias = ZonedDateTime | Time | time | tuple[int, int] | TimeDelta | int | float | None
"""Type for specifying start times."""
