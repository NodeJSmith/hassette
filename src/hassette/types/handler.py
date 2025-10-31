from collections.abc import Awaitable
from typing import Any, Protocol

from typing_extensions import TypeAliasType

from hassette.events.base import EventT


class SyncHandlerTypeNoEvent(Protocol):
    """Protocol for sync handlers that do not take an event argument."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...


class SyncHandler(Protocol[EventT]):
    """Protocol for sync handlers that take an event as first parameter."""

    def __call__(self, event: EventT, *args: Any, **kwargs: Any) -> Any: ...


class AsyncHandlerTypeNoEvent(Protocol):
    """Protocol for async handlers that do not take an event argument."""

    def __call__(self, *args: Any, **kwargs: Any) -> Awaitable[None]: ...


class AsyncHandler(Protocol[EventT]):
    """Protocol for async handlers that take an event as first parameter."""

    def __call__(self, event: EventT, *args: Any, **kwargs: Any) -> Awaitable[None]: ...


## Type Aliases ##

SyncHandlerTypeEvent = TypeAliasType("SyncHandlerTypeEvent", SyncHandler[EventT], type_params=(EventT,))
"""Alias for sync handler types that take an event argument."""


AsyncHandlerTypeEvent = TypeAliasType("AsyncHandlerTypeEvent", AsyncHandler[EventT], type_params=(EventT,))
"""Alias for async handler types that take an event argument."""

AsyncHandlerType = TypeAliasType(
    "AsyncHandlerType", AsyncHandlerTypeEvent[EventT] | AsyncHandlerTypeNoEvent, type_params=(EventT,)
)
"""Alias for all valid async handler types."""

HandlerTypeNoEvent = SyncHandlerTypeNoEvent | AsyncHandlerTypeNoEvent
"""Alias for all valid handler types that do not take an event argument."""

HandlerTypeEvent = TypeAliasType(
    "HandlerTypeEvent", SyncHandlerTypeEvent[EventT] | AsyncHandlerTypeEvent[EventT], type_params=(EventT,)
)
"""Alias for all valid handler types that take an event argument."""

HandlerType = TypeAliasType("HandlerType", HandlerTypeEvent[EventT] | HandlerTypeNoEvent, type_params=(EventT,))
"""Alias for all valid handler types."""
