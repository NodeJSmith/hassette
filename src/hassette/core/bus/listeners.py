import contextlib
import inspect
import typing
from dataclasses import dataclass
from functools import partial
from inspect import isawaitable
from types import MethodType
from typing import Any

if typing.TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from hassette.core.bus import Bus
    from hassette.core.events import Event
    from hassette.core.types import Predicate


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


@dataclass(slots=True)
class Listener:
    """A listener for events with a specific topic and handler."""

    key: str
    topic: str
    orig_handler: "Callable[[Event[Any]], Any]"
    handler: "Callable[[Event[Any]], Awaitable[None]]"  # fully wrapped, ready to await
    predicate: "Predicate | None"
    once: bool = False  # metadata for repr
    debounce: float | None = None
    throttle: float | None = None

    @property
    def handler_name(self) -> str:
        return callable_name(self.orig_handler)

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
        flag_s = f" [{', '.join(flags)}]" if flags else ""
        pred_s = "None" if self.predicate is None else type(self.predicate).__name__
        return f"Listener<{self.key} {self.topic} handler={self.handler_name} pred={pred_s}{flag_s}>"


@dataclass(slots=True)
class Subscription:
    """A subscription to an event topic with a specific listener key.

    This class is used to manage the lifecycle of a listener, allowing it to be cancelled
    or managed within a context.
    """

    bus: "Bus"
    topic: str
    key: str

    def unsubscribe(self) -> None:
        """Unsubscribe the listener from the bus."""
        self.bus.remove_listener_by_key(self.topic, self.key)

    @contextlib.contextmanager
    def manage(self):
        try:
            yield self
        finally:
            self.unsubscribe()
