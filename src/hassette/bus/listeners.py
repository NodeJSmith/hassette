import contextlib
import inspect
import itertools
import typing
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from logging import getLogger
from typing import Any, cast

from hassette.bus.injection import ParameterInjector
from hassette.bus.rate_limiter import RateLimiter
from hassette.event_handling.predicates import normalize_where
from hassette.utils.func_utils import callable_name, callable_short_name
from hassette.utils.type_utils import get_typed_signature

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from hassette import TaskBucket
    from hassette.events.base import Event
    from hassette.types import AsyncHandlerType, HandlerType, Predicate

LOGGER = getLogger(__name__)

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

    kwargs: Mapping[str, Any] | None = None
    """Keyword arguments to pass to the handler."""

    once: bool = False
    """Whether the listener should be removed after one invocation."""

    priority: int = 0
    """Priority for listener ordering. Higher values run first. Default is 0 for app handlers."""

    @property
    def handler_name(self) -> str:
        return callable_name(self.orig_handler)

    @property
    def handler_short_name(self) -> str:
        return callable_short_name(self.orig_handler)

    async def matches(self, ev: "Event[Any]") -> bool:
        """Check if the event matches the listener's predicate."""
        if self.predicate is None:
            return True
        return self.predicate(ev)

    async def invoke(self, event: "Event[Any]") -> None:
        """Invoke the handler through the adapter."""
        kwargs = self.kwargs or {}
        await self.adapter.call(event, **kwargs)

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
        kwargs: Mapping[str, Any] | None = None,
        once: bool = False,
        debounce: float | None = None,
        throttle: float | None = None,
        priority: int = 0,
    ) -> "Listener":
        pred = normalize_where(where)
        signature = get_typed_signature(handler)

        # Create async handler
        async_handler = make_async_handler(handler, task_bucket)

        # Create an adapter with rate limiting and signature informed calling
        adapter = HandlerAdapter(
            callable_name(handler),
            async_handler,
            signature,
            task_bucket,
            debounce=debounce,
            throttle=throttle,
        )

        return cls(
            owner=owner,
            topic=topic,
            orig_handler=handler,
            adapter=adapter,
            predicate=pred,
            kwargs=kwargs,
            once=once,
            priority=priority,
        )


class HandlerAdapter:
    """Handler adapter that composes dependency injection and rate limiting."""

    def __init__(
        self,
        handler_name: str,
        handler: "AsyncHandlerType",
        signature: inspect.Signature,
        task_bucket: "TaskBucket",
        debounce: float | None = None,
        throttle: float | None = None,
    ):
        self.handler_name = handler_name
        self.handler = handler
        self.task_bucket = task_bucket

        # Dependency injection setup
        self.injector = ParameterInjector(handler_name, signature)

        # Rate limiting setup
        self.rate_limiter: RateLimiter | None = None
        if debounce or throttle:
            if debounce and throttle:
                raise ValueError("Cannot specify both 'debounce' and 'throttle' parameters")
            self.rate_limiter = RateLimiter(
                task_bucket=task_bucket,
                debounce=debounce,
                throttle=throttle,
            )

    async def call(self, event: "Event[Any]", **kwargs: Any) -> None:
        """Call handler with dependency injection and optional rate limiting.

        Args:
            event: The event to pass to the handler.
            **kwargs: Additional keyword arguments to pass to the handler.

        Raises:
            DependencyInjectionError: If signature validation fails.
            DependencyResolutionError: If parameter extraction/conversion fails.
            Exception: If an error occurs during handler execution.
        """
        if self.rate_limiter:
            await self.rate_limiter.call(self._direct_call, event, **kwargs)
        else:
            await self._direct_call(event, **kwargs)

    async def _direct_call(self, event: "Event[Any]", **kwargs: Any) -> None:
        """Call handler directly with dependency injection (no rate limiting).

        Args:
            event: The event to pass to the handler.
            **kwargs: Additional keyword arguments to pass to the handler.
        """
        # Inject parameters
        kwargs = self.injector.inject_parameters(event, **kwargs)

        await self.handler(**kwargs)


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


def make_async_handler(fn: "HandlerType", task_bucket: "TaskBucket") -> "AsyncHandlerType":
    """Wrap a function to ensure it is always called as an async handler.

    If the function is already an async function, it will be called directly.
    If it is a regular function, it will be run in an executor to avoid blocking the event loop.

    Args:
        fn: The function to adapt.

    Returns:
        An async handler that wraps the original function.
    """
    return cast("AsyncHandlerType", task_bucket.make_async_adapter(fn))
