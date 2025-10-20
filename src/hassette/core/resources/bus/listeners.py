import asyncio
import contextlib
import inspect
import itertools
import time
import typing
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from inspect import Signature
from typing import Any, ParamSpec, TypeVar, cast

from hassette.utils.func_utils import callable_name

from .predicates.utils import normalize_where

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from hassette import TaskBucket
    from hassette.events import Event
    from hassette.types import (
        AsyncHandlerType,
        AsyncHandlerTypeEvent,
        AsyncHandlerTypeNoEvent,
        EventT,
        HandlerType,
        Predicate,
    )

PS = ParamSpec("PS")
RT = TypeVar("RT")

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

    signature: Signature
    """Signature of the original handler function."""

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

    @property
    def receives_event_arg(self) -> bool:
        """Determine if the handler function expects the event argument.

        If the handler takes no parameters, it does not receive the event. Otherwise,
        check if the first parameter is named 'event'.

        """
        return receives_event_arg(self.signature)

    async def matches(self, ev: "Event[Any]") -> bool:
        """Check if the event matches the listener's predicate."""
        if self.predicate is None:
            return True
        return self.predicate(ev)

    def __repr__(self) -> str:
        return f"Listener<{self.owner} - {self.handler_short_name}>"

    @classmethod
    def create(
        cls,
        task_bucket: "TaskBucket",
        owner: str,
        topic: str,
        handler: "HandlerType",
        where: "Predicate | Sequence[Predicate] | None" = None,
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
        once: bool = False,
        debounce: float | None = None,
        throttle: float | None = None,
    ) -> "Listener":
        pred = normalize_where(where)

        orig = handler

        signature = inspect.signature(orig)

        # ensure-async
        handler = make_async_handler(orig, task_bucket)

        # decorate
        if debounce and debounce > 0:
            handler = add_debounce(handler, debounce, signature, task_bucket)
        if throttle and throttle > 0:
            handler = add_throttle(handler, throttle, signature)

        return cls(
            owner=owner,
            topic=topic,
            orig_handler=orig,
            handler=handler,
            signature=signature,
            predicate=pred,
            args=args,
            kwargs=kwargs,
            once=once,
            debounce=debounce,
            throttle=throttle,
        )


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


def make_async_handler(fn: "HandlerType[EventT]", task_bucket: "TaskBucket") -> "AsyncHandlerType[EventT]":
    """Wrap a function to ensure it is always called as an async handler.

    If the function is already an async function, it will be called directly.
    If it is a regular function, it will be run in an executor to avoid blocking the event loop.

    Args:
        fn (Callable[..., Any]): The function to adapt.

    Returns:
        AsyncHandlerType: An async handler that wraps the original function.
    """
    return cast("AsyncHandlerType[EventT]", task_bucket.make_async_adapter(fn))


def add_debounce(
    handler: "AsyncHandlerType[Event[Any]]", seconds: float, signature: inspect.Signature, task_bucket: "TaskBucket"
) -> "AsyncHandlerType[Event[Any]]":
    """Add a debounce to an async handler.

    This will ensure that the handler is only called after a specified period of inactivity.
    If a new event comes in before the debounce period has passed, the previous call is cancelled.

    Args:
        handler (AsyncHandlerType): The async handler to debounce.
        seconds (float): The debounce period in seconds.
        signature (inspect.Signature): The signature of the original handler.
        task_bucket (TaskBucket): The task bucket to use for spawning tasks.

    Returns:
        AsyncHandlerType: A new async handler that applies the debounce logic.
    """
    pending: asyncio.Task | None = None
    last_ev: Event[Any] | None = None

    async def _debounced(event: "Event[Any]", *args: PS.args, **kwargs: PS.kwargs) -> None:
        nonlocal pending, last_ev
        last_ev = event
        if pending and not pending.done():
            pending.cancel()

        async def _later():
            try:
                await asyncio.sleep(seconds)
                if last_ev is not None:
                    if receives_event_arg(signature):
                        hdlr = cast("AsyncHandlerTypeEvent[Event[Any]]", handler)
                        await hdlr(last_ev, *args, **kwargs)
                    else:
                        hdlr = cast("AsyncHandlerTypeNoEvent", handler)
                        await hdlr(*args, **kwargs)
            except asyncio.CancelledError:
                pass

        pending = task_bucket.spawn(_later(), name="adapters:debounce_handler")

    return _debounced


def add_throttle(
    handler: "AsyncHandlerType[Event[Any]]", seconds: float, signature: inspect.Signature
) -> "AsyncHandlerType[Event[Any]]":
    """Add a throttle to an async handler.

    This will ensure that the handler is only called at most once every specified period of time.
    If a new event comes in before the throttle period has passed, it will be ignored.

    Args:
        handler (AsyncHandlerType): The async handler to throttle.
        seconds (float): The throttle period in seconds.
        signature (inspect.Signature): The signature of the original handler.

    Returns:
        AsyncHandlerType: A new async handler that applies the throttle logic.
    """

    last_time = 0.0
    lock = asyncio.Lock()

    async def _throttled(event: "Event[Any]", *args: PS.args, **kwargs: PS.kwargs) -> None:
        nonlocal last_time
        async with lock:
            now = time.monotonic()
            if now - last_time >= seconds:
                last_time = now
                if receives_event_arg(signature):
                    hdlr = cast("AsyncHandlerTypeEvent[Event[Any]]", handler)
                    await hdlr(event, *args, **kwargs)
                else:
                    hdlr = cast("AsyncHandlerTypeNoEvent", handler)
                    await hdlr(*args, **kwargs)

    return _throttled


def receives_event_arg(signature: inspect.Signature) -> bool:
    """Determine if the handler function expects the event argument.

    If the handler takes no parameters, it does not receive the event. Otherwise,
    check if the first parameter is named 'event'.

    """
    params = list(signature.parameters.values())
    if not params:
        return False
    first_param = params[0]
    return first_param.name == "event"
