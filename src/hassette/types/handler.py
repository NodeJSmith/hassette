import typing
from collections.abc import Awaitable
from typing import Any, Protocol, TypeVar

from typing_extensions import TypeAliasType

if typing.TYPE_CHECKING:
    from hassette.events import Event

EventT = TypeVar("EventT", bound="Event[Any]", contravariant=True)

V = TypeVar("V")  # value type from the accessor
V_contra = TypeVar("V_contra", contravariant=True)


class SyncHandlerNoEvent(Protocol):
    """Protocol for defining event handlers that do not take an event argument."""

    def __call__(self) -> Awaitable[None] | None: ...


class SyncHandlerNoEventVariadic(Protocol):
    """Protocol for defining event handlers that do not take an event argument and accept variadic parameters."""

    def __call__(self, *args: object, **kwargs: Any) -> Awaitable[None] | None: ...


class SyncHandler(Protocol[EventT]):
    """Protocol for defining event handlers that accept a single event parameter."""

    def __call__(self, event: EventT) -> Awaitable[None] | None: ...


class SyncHandlerVariadic(Protocol[EventT]):
    """Protocol for defining event handlers that accept variadic parameters."""

    def __call__(self, event: EventT, *args: object, **kwargs: Any) -> Awaitable[None] | None: ...


class AsyncHandlerNoEvent(Protocol):
    """Protocol for defining async event handlers that do not take an event argument."""

    def __call__(self) -> Awaitable[None]: ...


class AsyncHandlerNoEventVariadic(Protocol):
    """Protocol for defining async event handlers that do not take an event argument and accept variadic parameters."""

    def __call__(self, *args: object, **kwargs: Any) -> Awaitable[None]: ...


class AsyncHandler(Protocol[EventT]):
    """Protocol for defining async event handlers."""

    def __call__(self, event: EventT) -> Awaitable[None]: ...


class AsyncHandlerVariadic(Protocol[EventT]):
    """Protocol for defining async event handlers that accept variadic parameters."""

    def __call__(self, event: EventT, *args: object, **kwargs: Any) -> Awaitable[None]: ...


## Sync Handler Types ##

SyncHandlerTypeNoEvent = SyncHandlerNoEvent | SyncHandlerNoEventVariadic
"""Alias for sync handler types that do not take an event argument."""

SyncHandlerTypeEvent = TypeAliasType(
    "SyncHandlerTypeEvent", SyncHandler[EventT] | SyncHandlerVariadic[EventT], type_params=(EventT,)
)
"""Alias for all valid sync handler types."""

SyncHandlerType = TypeAliasType(
    "SyncHandlerType", SyncHandlerTypeEvent[EventT] | SyncHandlerTypeNoEvent, type_params=(EventT,)
)
"""Alias for all valid sync handler types."""

## Async Handler Types ##

AsyncHandlerTypeNoEvent = AsyncHandlerNoEvent | AsyncHandlerNoEventVariadic
"""Alias for async handler types that do not take an event argument."""

AsyncHandlerTypeEvent = TypeAliasType(
    "AsyncHandlerTypeEvent", AsyncHandler[EventT] | AsyncHandlerVariadic[EventT], type_params=(EventT,)
)
"""Alias for all valid async handler types."""

AsyncHandlerType = TypeAliasType(
    "AsyncHandlerType", AsyncHandlerTypeEvent[EventT] | AsyncHandlerTypeNoEvent, type_params=(EventT,)
)
"""Alias for all valid async handler types."""

## Combined Handler Types ##

HandlerTypeNoEvent = SyncHandlerTypeNoEvent | AsyncHandlerTypeNoEvent
"""Alias for all valid handler types that do not take an event argument."""

HandlerTypeEvent = TypeAliasType(
    "HandlerTypeEvent", SyncHandlerTypeEvent[EventT] | AsyncHandlerTypeEvent[EventT], type_params=(EventT,)
)
"""Alias for all valid handler types that take an event argument."""

HandlerType = TypeAliasType("HandlerType", HandlerTypeEvent[EventT] | HandlerTypeNoEvent, type_params=(EventT,))
"""Alias for all valid handler types."""
