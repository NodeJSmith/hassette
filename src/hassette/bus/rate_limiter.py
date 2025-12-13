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

    Debounce: Delays execution until after a period of inactivity.
    Throttle: Ensures execution happens at most once per time period.

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

        Raises:
            ValueError: If both debounce and throttle are specified.
        """
        if debounce and throttle:
            raise ValueError("Cannot specify both 'debounce' and 'throttle' parameters")

        self.task_bucket = task_bucket
        self.debounce = debounce
        self.throttle = throttle

        # Rate limiting state
        self._debounce_task: asyncio.Task | None = None
        self._throttle_last_time = 0.0
        self._throttle_lock = asyncio.Lock()

    async def call(self, handler: "Callable", *args: Any, **kwargs: Any) -> None:
        """Call handler with rate limiting applied.

        Args:
            handler: The async handler to call.
            *args: Positional arguments to pass to handler.
            **kwargs: Keyword arguments to pass to handler.
        """
        if self.debounce:
            await self._debounced_call(handler, *args, **kwargs)
        elif self.throttle:
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
                await handler(*args, **kwargs)
            except asyncio.CancelledError:
                # Task was cancelled (e.g., due to a new debounce call); safe to ignore.
                pass

        self._debounce_task = self.task_bucket.spawn(delayed_call(), name="handler:debounce")

    async def _throttled_call(self, handler: "Callable", *args: Any, **kwargs: Any) -> None:
        """Throttled version of the handler call."""
        if self.throttle is None:
            raise ValueError("Throttle value is not set")

        async with self._throttle_lock:
            now = time.monotonic()
            if now - self._throttle_last_time >= self.throttle:
                self._throttle_last_time = now
                await handler(*args, **kwargs)
