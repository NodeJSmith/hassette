"""Rate limiting for event handler calls."""

import asyncio
import time
import typing
from logging import getLogger

if typing.TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from hassette import TaskBucket
    from hassette.bus.listeners import DropReporter
    from hassette.events.base import AnyEvent

LOGGER = getLogger(__name__)


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
        await limiter.call(invoke_fn, event)  # invoke_fn is a zero-arg async closure
        ```
    """

    def __init__(
        self,
        task_bucket: "TaskBucket",
        debounce: float | None = None,
        throttle: float | None = None,
        handler_name: str = "unknown",
        clock: "Callable[[], float] | None" = None,
    ) -> None:
        """Initialize the rate limiter.

        Args:
            task_bucket: TaskBucket for spawning background tasks.
            debounce: Debounce delay in seconds.
            throttle: Throttle interval in seconds.
            handler_name: Name of the owning handler, used in log messages for diagnostics.
            clock: Zero-arg callable returning the current monotonic time, used for throttle
                timestamps. Defaults to ``time.monotonic``. Injectable for deterministic tests.
        """
        self.task_bucket = task_bucket
        self.debounce = debounce
        self.throttle = throttle
        self.handler_name = handler_name
        self._clock = clock or time.monotonic

        self._debounce_task: asyncio.Task[None] | None = None
        self._debounce_event: AnyEvent | None = None
        """The event the pending debounce task is holding, reported as superseded if a later event replaces it."""
        self._debounce_report: DropReporter | None = None
        """The reporter passed with ``_debounce_event``."""
        self._throttle_last_time: float | None = None
        self._cancelled = False

    def clear_debounce_ref(self, task: "asyncio.Task[None]") -> None:
        """Done callback: clear _debounce_task if it's still the current task."""
        if self._debounce_task is task:
            self._debounce_task = None
            self._debounce_event = self._debounce_report = None

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
        self._debounce_event = self._debounce_report = None

    async def call(
        self,
        handler: "Callable[[], Awaitable[None]]",
        event: "AnyEvent",
        report: "DropReporter | None" = None,
    ) -> None:
        """Call handler with rate limiting applied.

        Args:
            handler: Zero-arg async callable.  ``Listener.dispatch()`` always passes a
                closure that captures the event and error handling internally.
            event: The event ``handler`` runs for.
            report: Called with an event this limiter drops: ``throttled`` for one inside the throttle window,
                ``debounce_superseded`` for a pending event a later one replaces. None records nothing.
        """
        if self._cancelled:
            return
        if self.debounce is not None:
            await self.debounced_call(handler, self.debounce, event, report)
        elif self.throttle is not None:
            await self.throttled_call(handler, self.throttle, event, report)
        else:
            await handler()

    async def debounced_call(
        self,
        handler: "Callable[[], Awaitable[None]]",
        debounce: float,
        event: "AnyEvent | None" = None,
        report: "DropReporter | None" = None,
    ) -> None:
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
            LOGGER.debug("Debounce reset for handler=%s (window=%.1fs)", self.handler_name, debounce)
            self._debounce_task.cancel()
            if self._debounce_report is not None and self._debounce_event is not None:
                self._debounce_report("debounce_superseded", self._debounce_event)

        async def delayed_call() -> None:
            try:
                await asyncio.sleep(debounce)
            except asyncio.CancelledError:  # noqa: ASYNC103 — debounce reset: a new event superseded this one
                return  # noqa: ASYNC104
            # Guard: if cancel() was called while we were sleeping, don't fire the handler.
            if self._cancelled:
                return
            # Quiet period over: from here this is a running invocation, not a pending timer.
            # Dropping the reference keeps the next debounce reset (and cancel()) from
            # cancelling the handler mid-run; the execution mode and task bucket own it now.
            self._debounce_task = None
            self._debounce_event = self._debounce_report = None
            # Handler runs outside the CancelledError catch — if the handler is cancelled
            # (e.g., during shutdown), it propagates so telemetry can record it as 'cancelled'.
            await handler()

        task = self.task_bucket.spawn(delayed_call(), name="handler:debounce")
        task.add_done_callback(self.clear_debounce_ref)
        self._debounce_task = task
        self._debounce_event = event
        self._debounce_report = report

    async def throttled_call(
        self,
        handler: "Callable[[], Awaitable[None]]",
        throttle: float,
        event: "AnyEvent | None" = None,
        report: "DropReporter | None" = None,
    ) -> None:
        """Throttled version of the handler call.

        At most one attempt per window. No lock needed — the check-and-set between
        ``self._clock()`` and ``self._throttle_last_time = now`` is atomic in asyncio's
        single-threaded event loop (no await point between them).
        """
        now = self._clock()
        if self._throttle_last_time is not None and now - self._throttle_last_time < throttle:
            LOGGER.debug("Throttle drop for handler=%s (window=%.1fs)", self.handler_name, throttle)
            if report is not None and event is not None:
                report("throttled", event)
            return
        self._throttle_last_time = now
        await handler()
