"""Rate limiting for event handler calls."""

import asyncio
import time
import typing
from typing import Any

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from hassette import TaskBucket


class RateLimiter:
    """Handles rate limiting for handler calls using debounce or throttle strategies.

    Debounce: Delays execution until after a period of inactivity. When a new call
    arrives during the debounce window, the previous timer is cancelled and restarted.

    Throttle: At most one execution per window. Calls arriving within the window are
    silently dropped (not queued). The handler executes outside any lock — no lock is
    needed because the check-and-set is atomic within asyncio's single-threaded event loop.

    Attributes:
        debounce: Debounce delay in seconds, or None.
        throttle: Throttle interval in seconds, or None.

    Example:
        ```python
        limiter = RateLimiter(debounce=1.0)
        await limiter.call(handler, event=event)
        ```
    """

    def __init__(
        self,
        task_bucket: "TaskBucket",
        debounce: float | None = None,
        throttle: float | None = None,
    ):
        """Initialize the rate limiter.

        Args:
            task_bucket: TaskBucket for spawning background tasks.
            debounce: Debounce delay in seconds.
            throttle: Throttle interval in seconds.

        """
        self.task_bucket = task_bucket
        self.debounce = debounce
        self.throttle = throttle

        # Rate limiting state
        self._debounce_task: asyncio.Task | None = None
        self._throttle_last_time = 0.0
        self._cancelled = False

    def cancel(self) -> None:
        """Cancel any pending debounce task.

        Called when a listener is removed to prevent dangling tasks from holding
        references to handler objects after the listener's lifecycle has ended.

        This is a terminal operation -- the RateLimiter should not be reused after cancel().
        """
        self._cancelled = True
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
            self._debounce_task = None

    async def call(self, handler: "Callable", *args: Any, **kwargs: Any) -> None:
        """Call handler with rate limiting applied.

        Args:
            handler: The async handler to call.
            *args: Positional arguments to pass to handler.
            **kwargs: Keyword arguments to pass to handler.
        """
        if self.debounce is not None:
            await self._debounced_call(handler, *args, **kwargs)
        elif self.throttle is not None:
            await self._throttled_call(handler, *args, **kwargs)
        else:
            await handler(*args, **kwargs)

    async def _debounced_call(self, handler: "Callable", *args: Any, **kwargs: Any) -> None:
        """Debounced version of the handler call."""
        # Cancel previous debounce

        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()

        async def delayed_call():
            if self.debounce is None:
                raise ValueError("Debounce value is not set")

            try:
                await asyncio.sleep(self.debounce)
            except asyncio.CancelledError:
                # Debounce reset: a new event superseded this one. Silent and expected.
                return
            # Guard: if cancel() was called while we were sleeping, don't fire the handler.
            if self._cancelled:
                return
            # Handler runs outside the CancelledError catch — if the handler is cancelled
            # (e.g., during shutdown), it propagates so telemetry can record it as 'cancelled'.
            await handler(*args, **kwargs)

        task = self.task_bucket.spawn(delayed_call(), name="handler:debounce")
        # Clear reference after completion to release captured event payloads.
        # Only clear if this is still the current task (a newer debounce may have replaced it).
        task.add_done_callback(lambda t: setattr(self, "_debounce_task", None) if self._debounce_task is t else None)
        self._debounce_task = task

    async def _throttled_call(self, handler: "Callable", *args: Any, **kwargs: Any) -> None:
        """Throttled version of the handler call.

        At most one attempt per window. No lock needed — the check-and-set between
        ``time.monotonic()`` and ``self._throttle_last_time = now`` is atomic in asyncio's
        single-threaded event loop (no await point between them).
        """
        if self.throttle is None:
            raise ValueError("Throttle value is not set")

        now = time.monotonic()
        if now - self._throttle_last_time < self.throttle:
            return
        self._throttle_last_time = now
        await handler(*args, **kwargs)
