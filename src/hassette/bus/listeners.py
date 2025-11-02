import asyncio
import contextlib
import inspect
import itertools
import time
import typing
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ParamSpec, TypeVar, cast

from hassette.utils.func_utils import callable_name

from .utils import normalize_where

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from hassette import TaskBucket
    from hassette.events.base import Event, EventT
    from hassette.types import (
        AsyncHandlerType,
        AsyncHandlerTypeEvent,
        AsyncHandlerTypeNoEvent,
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

    adapter: "HandlerAdapter"
    """Handler adapter that manages signature normalization and rate limiting."""

    predicate: "Predicate | None"
    """Predicate to filter events before invoking the handler."""

    args: tuple[Any, ...] | None = None
    """Positional arguments to pass to the handler."""

    kwargs: Mapping[str, Any] | None = None
    """Keyword arguments to pass to the handler."""

    once: bool = False
    """Whether the listener should be removed after one invocation."""

    @property
    def handler_name(self) -> str:
        return callable_name(self.orig_handler)

    @property
    def handler_short_name(self) -> str:
        return self.handler_name.split(".")[-1]

    async def matches(self, ev: "Event[Any]") -> bool:
        """Check if the event matches the listener's predicate."""
        if self.predicate is None:
            return True
        return self.predicate(ev)

    async def invoke(self, event: "Event[Any]") -> None:
        """Invoke the handler through the adapter."""
        args = self.args or ()
        kwargs = self.kwargs or {}
        await self.adapter.call(event, *args, **kwargs)

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
        signature = inspect.signature(handler)

        # Create async handler
        async_handler = make_async_handler(handler, task_bucket)

        # Create an adapter with rate limiting and signature informed calling
        adapter = HandlerAdapter(async_handler, signature, task_bucket, debounce=debounce, throttle=throttle)

        return cls(
            owner=owner,
            topic=topic,
            orig_handler=handler,
            adapter=adapter,
            predicate=pred,
            args=args,
            kwargs=kwargs,
            once=once,
        )


class HandlerAdapter:
    """Unified handler adapter that handles signature normalization and rate limiting."""

    def __init__(
        self,
        handler: "AsyncHandlerType",
        signature: inspect.Signature,
        task_bucket: "TaskBucket",
        debounce: float | None = None,
        throttle: float | None = None,
    ):
        if debounce and throttle:
            raise ValueError("Cannot specify both 'debounce' and 'throttle' parameters")

        self.handler = handler
        self.signature = signature
        self.task_bucket = task_bucket
        self.expects_event = self._receives_event_arg()

        # Rate limiting state
        self._debounce_task: asyncio.Task | None = None
        self._throttle_last_time = 0.0
        self._throttle_lock = asyncio.Lock()

        # Apply rate limiting
        if debounce and debounce > 0:
            self.call = self._make_debounced_call(debounce)
        elif throttle and throttle > 0:
            self.call = self._make_throttled_call(throttle)
        else:
            self.call = self._direct_call

    def _receives_event_arg(self) -> bool:
        """Check if handler expects an event argument."""
        params = list(self.signature.parameters.values())
        if not params:
            return False
        first_param = params[0]
        return first_param.name == "event" and first_param.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )

    async def _direct_call(self, event: "Event[Any]", *args: Any, **kwargs: Any) -> None:
        """Call handler directly with appropriate signature."""
        if self.expects_event:
            handler = cast("AsyncHandlerTypeEvent[Event[Any]]", self.handler)
            await handler(event, *args, **kwargs)
        else:
            handler = cast("AsyncHandlerTypeNoEvent", self.handler)
            await handler(*args, **kwargs)

    def _make_debounced_call(self, seconds: float):
        """Create a debounced version of the call method."""

        async def debounced_call(event: "Event[Any]", *args: Any, **kwargs: Any) -> None:
            # Cancel previous debounce
            if self._debounce_task and not self._debounce_task.done():
                self._debounce_task.cancel()

            async def delayed_call():
                try:
                    await asyncio.sleep(seconds)
                    await self._direct_call(event, *args, **kwargs)
                except asyncio.CancelledError:
                    pass

            self._debounce_task = self.task_bucket.spawn(delayed_call(), name="handler:debounce")

        return debounced_call

    def _make_throttled_call(self, seconds: float):
        """Create a throttled version of the call method."""

        async def throttled_call(event: "Event[Any]", *args: Any, **kwargs: Any) -> None:
            async with self._throttle_lock:
                now = time.monotonic()
                if now - self._throttle_last_time >= seconds:
                    self._throttle_last_time = now
                    await self._direct_call(event, *args, **kwargs)

        return throttled_call


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
        fn: The function to adapt.

    Returns:
        An async handler that wraps the original function.
    """
    return cast("AsyncHandlerType[EventT]", task_bucket.make_async_adapter(fn))
