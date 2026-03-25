"""Rate limiting for event handler calls."""

import asyncio
import time
import typing
from logging import getLogger

if typing.TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from hassette import TaskBucket

_logger = getLogger(__name__)


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
        limiter = RateLimiter(task_bucket=bucket, debounce=1.0, handler_name="my_handler")
        await limiter.call(handler, event=event)
        ```
    """

    def __init__(
        self,
        task_bucket: "TaskBucket",
        debounce: float | None = None,
        throttle: float | None = None,
        handler_name: str = "unknown",
    ):
        """Initialize the rate limiter.

        Args:
            task_bucket: TaskBucket for spawning background tasks.
            debounce: Debounce delay in seconds.
            throttle: Throttle interval in seconds.
            handler_name: Name of the owning handler, used in log messages for diagnostics.

        """
        self.task_bucket = task_bucket
        self.debounce = debounce
        self.throttle = throttle
        self._handler_name = handler_name

        # Rate limiting state
        self._debounce_task: asyncio.Task | None = None
        self._throttle_last_time = 0.0
        self._cancelled = False

    def _clear_debounce_ref(self, task: "asyncio.Task[None]") -> None:
        """Done callback: clear _debounce_task if it's still the current task."""
        if self._debounce_task is task:
            self._debounce_task = None

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

    async def call(self, handler: "Callable[[], Awaitable[None]]") -> None:
        """Call handler with rate limiting applied.

        Args:
            handler: Zero-arg async callable.  ``Listener.dispatch()`` always passes a
                closure that captures the event and error handling internally.
        """
        if self._cancelled:
            return
        if self.debounce is not None:
            await self._debounced_call(handler)
        elif self.throttle is not None:
            await self._throttled_call(handler)
        else:
            await handler()

    async def _debounced_call(self, handler: "Callable[[], Awaitable[None]]") -> None:
        """Debounced version of the handler call.

        Expects a fresh ``handler`` callable on each call.  BusService creates a new
        closure per dispatch that captures the current event, so the debounced handler
        always fires with the latest event data.  Callers must not reuse the same
        callable with updated shared state — the cancel-then-create ordering below
        discards the previous handler entirely.
        """
        # Cancel previous debounce task BEFORE spawning the replacement.  This ordering
        # is critical: the old task holds the old handler closure (with the old event),
        # and the new task will hold the new handler closure (with the latest event).
        if self._debounce_task and not self._debounce_task.done():
            _logger.debug("Debounce reset for handler=%s (window=%.1fs)", self._handler_name, self.debounce)
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
            await handler()

        task = self.task_bucket.spawn(delayed_call(), name="handler:debounce")
        task.add_done_callback(self._clear_debounce_ref)
        self._debounce_task = task

    async def _throttled_call(self, handler: "Callable[[], Awaitable[None]]") -> None:
        """Throttled version of the handler call.

        At most one attempt per window. No lock needed — the check-and-set between
        ``time.monotonic()`` and ``self._throttle_last_time = now`` is atomic in asyncio's
        single-threaded event loop (no await point between them).
        """
        if self.throttle is None:
            raise ValueError("Throttle value is not set")

        now = time.monotonic()
        if now - self._throttle_last_time < self.throttle:
            _logger.debug("Throttle drop for handler=%s (window=%.1fs)", self._handler_name, self.throttle)
            return
        self._throttle_last_time = now
        await handler()
