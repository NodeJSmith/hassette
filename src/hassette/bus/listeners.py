import asyncio
import contextlib
import inspect
import itertools
import time
import typing
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from logging import getLogger
from typing import Any, cast

from hassette.dependencies.extraction import extract_from_signature, validate_di_signature
from hassette.exceptions import (
    CallListenerError,
    InvalidDependencyInjectionSignatureError,
    InvalidDependencyReturnTypeError,
    UnableToExtractParameterError,
)
from hassette.utils.exception_utils import get_short_traceback
from hassette.utils.func_utils import callable_name, callable_short_name
from hassette.utils.type_utils import get_optional_type_arg, get_typed_signature, is_optional_type

from .utils import extract_with_error_handling, normalize_where, warn_or_raise_on_incorrect_type

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
    """Unified handler adapter that handles signature normalization and rate limiting."""

    def __init__(
        self,
        handler_name: str,
        handler: "AsyncHandlerType",
        signature: inspect.Signature,
        task_bucket: "TaskBucket",
        debounce: float | None = None,
        throttle: float | None = None,
    ):
        if debounce and throttle:
            raise ValueError("Cannot specify both 'debounce' and 'throttle' parameters")

        self.handler_name = handler_name
        self.handler = handler
        self.signature = signature
        self.task_bucket = task_bucket

        validate_di_signature(signature)

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

    async def _direct_call(self, event: "Event[Any]", **kwargs: Any) -> None:
        """Call handler with dependency injection.

        Extracts required parameters from the event using type annotations
        and injects them as kwargs.

        Args:
            event: The event to pass to the handler.
            **kwargs: Additional keyword arguments to pass to the handler.

        Raises:
            CallListenerError: If an error occurs during handler execution.
            UnableToExtractParameterError: If parameter extraction fails.
        """

        kwargs = convert_params(self.handler_name, event, self.signature, **kwargs)

        # actually execute the call

        try:
            await self.handler(**kwargs)
        except CallListenerError:
            raise
        except Exception as e:
            LOGGER.error("Error while executing handler %s: %s", self.handler_name, get_short_traceback())
            raise CallListenerError(f"Error while executing handler {self.handler_name}") from e

    def _make_debounced_call(self, seconds: float):
        """Create a debounced version of the call method."""

        async def debounced_call(event: "Event[Any]", **kwargs: Any) -> None:
            # Cancel previous debounce
            if self._debounce_task and not self._debounce_task.done():
                self._debounce_task.cancel()

            async def delayed_call():
                try:
                    await asyncio.sleep(seconds)
                    await self._direct_call(event, **kwargs)
                except asyncio.CancelledError:
                    pass

            self._debounce_task = self.task_bucket.spawn(delayed_call(), name="handler:debounce")

        return debounced_call

    def _make_throttled_call(self, seconds: float):
        """Create a throttled version of the call method."""

        async def throttled_call(event: "Event[Any]", **kwargs: Any) -> None:
            async with self._throttle_lock:
                now = time.monotonic()
                if now - self._throttle_last_time >= seconds:
                    self._throttle_last_time = now
                    await self._direct_call(event, **kwargs)

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


def convert_params(handler_name: str, event: "Event[Any]", signature: inspect.Signature, **kwargs) -> dict[str, Any]:
    """Extract parameters for the handler based on its signature and the event.

    Args:
        handler_name: The name of the handler function.
        event: The event to extract parameters from.
        signature: The signature of the handler function.
        **kwargs: Additional keyword arguments to pass to the handler.

    Returns:
        A dictionary of parameters to pass to the handler.

    Raises:
        CallListenerError: If parameter extraction or conversion fails.
    """

    try:
        param_details = extract_from_signature(signature)

        for param_name, (param_type, annotation_details) in param_details.items():
            if param_name in kwargs:
                LOGGER.warning("Parameter '%s' provided in kwargs will be overridden by DI", param_name)

            extractor = annotation_details.extractor
            converter = annotation_details.converter

            extracted_value = extract_with_error_handling(event, extractor, param_name, param_type, handler_name)
            param_is_optional = is_optional_type(param_type)

            if param_is_optional and extracted_value is None:
                kwargs[param_name] = None
                continue

            if param_is_optional:
                param_type = get_optional_type_arg(param_type)

            if converter:
                extracted_value = converter(extracted_value, param_type)

            warn_or_raise_on_incorrect_type(param_name, param_type, extracted_value, handler_name)
            kwargs[param_name] = extracted_value

    except InvalidDependencyReturnTypeError as e:
        LOGGER.error("Handler '%s' - dependency returned invalid type: '%s'", handler_name, e.resolved_type)
        raise CallListenerError(
            f"Listener '{handler_name}' cannot be called due to invalid dependency: "
            f"expected '{param_type}', got '{e.resolved_type}'"
        ) from e

    except InvalidDependencyInjectionSignatureError as e:
        LOGGER.error("Handler '%s' has invalid DI signature: %s", handler_name, e)
        raise CallListenerError(f"Listener '{handler_name}' cannot be called due to invalid DI signature") from e

    except UnableToExtractParameterError as e:
        LOGGER.error(
            "Handler '%s' - unable to extract parameter '%s' of type '%s': %s",
            handler_name,
            param_name,
            param_type,
            get_short_traceback(),
        )
        raise CallListenerError(
            f"Listener {handler_name} cannot be called due to extraction error for parameter '{param_name}'"
        ) from e

    return kwargs
