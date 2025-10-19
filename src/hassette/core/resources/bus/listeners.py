import contextlib
import itertools
import typing
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from hassette.utils.func_utils import callable_name

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from hassette.events import Event
    from hassette.types import AsyncHandlerType, HandlerType, Predicate


seq = itertools.count(1)


def next_id() -> int:
    return next(seq)


@dataclass(slots=True)
class Listener:
    """A listener for events with a specific topic and handler."""

    listener_id: int = field(default_factory=next_id, init=False)
    """Unique identifier for the listener instance."""

    owner: str = field(compare=False)
    """Unique string identifier for the owner of the listener, e.g., a component or integration name."""

    topic: str
    """Topic the listener is subscribed to."""

    orig_handler: "HandlerType"
    """Original handler function provided by the user."""

    handler: "AsyncHandlerType"
    """Wrapped handler function that is always async."""

    predicate: "Predicate | None"
    """Predicate to filter events before invoking the handler."""

    args: tuple[Any, ...] | None = None
    """Positional arguments to pass to the handler."""

    kwargs: Mapping[str, Any] | None = None
    """Keyword arguments to pass to the handler."""

    once: bool = False
    """Whether the listener should be removed after one invocation."""

    debounce: float | None = None
    """Debounce interval in seconds, or None if not debounced."""

    throttle: float | None = None
    """Throttle interval in seconds, or None if not throttled."""

    @property
    def handler_name(self) -> str:
        return callable_name(self.orig_handler)

    @property
    def handler_short_name(self) -> str:
        return self.handler_name.split(".")[-1]

    async def matches(self, ev: "Event[Any]") -> bool:
        if self.predicate is None:
            return True
        return self.predicate(ev)

    def __repr__(self) -> str:
        return f"Listener<{self.owner} - {self.handler_short_name}>"


@dataclass(slots=True)
class Subscription:
    """A subscription to an event topic with a specific listener key.

    This class is used to manage the lifecycle of a listener, allowing it to be cancelled
    or managed within a context.
    """

    listener: Listener
    """The listener associated with this subscription."""

    unsubscribe: "Callable[[], None]"
    """Function to call to unsubscribe the listener."""

    @contextlib.contextmanager
    def manage(self):
        try:
            yield self
        finally:
            self.unsubscribe()

    def cancel(self) -> None:
        """Cancel the subscription by calling the unsubscribe function."""
        self.unsubscribe()
