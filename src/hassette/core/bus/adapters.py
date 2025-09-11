import asyncio
import time
import typing
from typing import Any, cast

from hassette.async_utils import make_async_adapter
from hassette.core.events import Event

if typing.TYPE_CHECKING:
    from hassette.core.core import Hassette
    from hassette.core.types import AsyncHandler, E_contra, Handler


def make_async_handler(fn: "Handler[E_contra]") -> "AsyncHandler[E_contra]":
    """Wrap a function to ensure it is always called as an async handler.

    If the function is already an async function, it will be called directly.
    If it is a regular function, it will be run in an executor to avoid blocking the event loop.

    Args:
        fn (Callable[..., Any]): The function to adapt.

    Returns:
        AsyncHandler: An async handler that wraps the original function.
    """
    return cast("AsyncHandler[E_contra]", make_async_adapter(fn))


def add_debounce(
    handler: "AsyncHandler[Event[Any]]", seconds: float, hassette: "Hassette"
) -> "AsyncHandler[Event[Any]]":
    """Add a debounce to an async handler.

    This will ensure that the handler is only called after a specified period of inactivity.
    If a new event comes in before the debounce period has passed, the previous call is cancelled.

    Args:
        handler (AsyncHandler): The async handler to debounce.
        seconds (float): The debounce period in seconds.

    Returns:
        AsyncHandler: A new async handler that applies the debounce logic.
    """
    pending: asyncio.Task | None = None
    last_ev: Event[Any] | None = None

    async def _debounced(event: Event[Any]) -> None:
        nonlocal pending, last_ev
        last_ev = event
        if pending and not pending.done():
            pending.cancel()

        async def _later():
            try:
                await asyncio.sleep(seconds)
                if last_ev is not None:
                    await handler(last_ev)
            except asyncio.CancelledError:
                pass

        pending = hassette.create_task(_later())

    return _debounced


def add_throttle(handler: "AsyncHandler[Event[Any]]", seconds: float) -> "AsyncHandler[Event[Any]]":
    """Add a throttle to an async handler.

    This will ensure that the handler is only called at most once every specified period of time.
    If a new event comes in before the throttle period has passed, it will be ignored.

    Args:
        handler (AsyncHandler): The async handler to throttle.
        seconds (float): The throttle period in seconds.

    Returns:
        AsyncHandler: A new async handler that applies the throttle logic.
    """

    last_time = 0.0
    lock = asyncio.Lock()

    async def _throttled(event: Event[Any]) -> None:
        nonlocal last_time
        async with lock:
            now = time.monotonic()
            if now - last_time >= seconds:
                last_time = now
                await handler(event)

    return _throttled
