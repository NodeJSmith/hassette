import contextlib
import inspect
import itertools
import typing
from dataclasses import dataclass, field
from functools import lru_cache, partial
from inspect import isawaitable
from types import MethodType
from typing import Any

if typing.TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from hassette.events import Event
    from hassette.types import Predicate


seq = itertools.count(1)


def next_id() -> int:
    return next(seq)


@lru_cache(maxsize=1024)
def callable_name(fn: Any) -> str:
    """Get a human-readable name for a callable object.

    This function attempts to return a string representation of the callable that includes
    its module, class (if applicable), and function name. It handles various types of callables
    including functions, methods, and partials.

    Args:
        fn (Any): The callable object to inspect.

    Returns:
        str: A string representation of the callable.
    """
    # unwrap decorator chains
    with contextlib.suppress(Exception):
        fn = inspect.unwrap(fn)

    # functools.partial
    if isinstance(fn, partial):
        return f"partial({callable_name(fn.func)})"

    # bound method
    if isinstance(fn, MethodType):
        self_obj = fn.__self__
        cls = type(self_obj).__name__
        return f"{self_obj.__module__}.{cls}.{fn.__name__}"

    # plain function
    if hasattr(fn, "__qualname__"):
        mod = getattr(fn, "__module__", None) or "<unknown>"
        return f"{mod}.{fn.__qualname__}"

    # callable object
    if callable(fn):
        cls = type(fn).__name__
        mod = type(fn).__module__
        return f"{mod}.{cls}.__call__"

    return repr(fn)


def callable_short_name(fn: Any) -> str:
    full_name = callable_name(fn)
    return full_name.split(".")[-1]


@dataclass(slots=True)
class Listener:
    """A listener for events with a specific topic and handler."""

    listener_id: int = field(default_factory=next_id, init=False)
    """Unique identifier for the listener instance."""

    owner: str = field(compare=False)
    """Unique string identifier for the owner of the listener, e.g., a component or integration name."""

    topic: str
    """Topic the listener is subscribed to."""

    orig_handler: "Callable[[Event[Any]], Any]"
    """Original handler function provided by the user."""

    handler: "Callable[[Event[Any]], Awaitable[None]]"  # fully wrapped, ready to await
    """Wrapped handler function that is always async."""

    predicate: "Predicate | None"
    """Predicate to filter events before invoking the handler."""

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
        res = self.predicate(ev)  # type: ignore
        if isawaitable(res):
            return await res
        return bool(res)

    def __repr__(self) -> str:
        flags = []
        if self.once:
            flags.append("once")
        if self.debounce:
            flags.append(f"debounce={self.debounce}")
        if self.throttle:
            flags.append(f"throttle={self.throttle}")
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
