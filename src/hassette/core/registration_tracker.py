"""Standalone tracker for pending DB registration tasks.

Encapsulates the prune-and-track, await-with-timeout, and drain patterns
that were previously duplicated in BusService and SchedulerService.

This class has NO dependency on Resource or Service — it is a plain utility.
"""

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from logging import Logger

from hassette.types.types import is_framework_key


class RegistrationTracker:
    """Tracks pending DB registration tasks per app_key.

    Provides a unified barrier (await_complete) that uses ``asyncio.wait()``
    to correctly report the number of incomplete tasks before cancelling
    stragglers on timeout.
    """

    _tasks: dict[str, list[asyncio.Task[None]]]

    def __init__(self) -> None:
        self._tasks = defaultdict(list)

    def prune_and_track(self, app_key: str, task: asyncio.Task[None]) -> None:
        """Prune completed tasks for *app_key*, then append *task*.

        Prevents unbounded list growth for apps that register listeners or
        jobs dynamically after startup.
        """
        existing = self._tasks.get(app_key)
        if existing:
            self._tasks[app_key] = [t for t in existing if not t.done()]
        self._tasks[app_key].append(task)

    async def await_complete(self, app_key: str, timeout: float, logger: Logger) -> None:
        """Wait for all pending registration tasks for *app_key* to complete.

        Uses ``asyncio.wait(..., timeout=)`` so the set of still-pending tasks
        is available *before* cancellation — the warning message reports the
        correct incomplete count (fixes the BusService bug where
        ``asyncio.wait_for(asyncio.gather(...))`` always reported 0).

        Args:
            app_key: The app key whose pending registration tasks to await.
            timeout: Maximum seconds to wait.
            logger: Logger for the warning message on timeout.
        """
        tasks = self._tasks.pop(app_key, [])
        if not tasks:
            return

        pending = [t for t in tasks if not t.done()]
        if not pending:
            return

        _done, still_pending = await asyncio.wait(pending, timeout=timeout)
        if still_pending:
            for task in still_pending:
                task.cancel()
            await asyncio.wait(still_pending, timeout=1.0)
            logger.warning(
                "await_registrations_complete timed out after %ss for app_key=%r — "
                "%d registration task(s) incomplete; those registrations will be excluded from live IDs",
                timeout,
                app_key,
                len(still_pending),
            )

    async def drain_framework_keys(self, await_fn: Callable[[str], Awaitable[None]]) -> None:
        """Call *await_fn* for each framework-prefixed key.

        Takes a snapshot of keys via ``list()`` to prevent RuntimeError if a
        concurrent coroutine mutates the dict during iteration.
        """
        for key in list(self._tasks):
            if is_framework_key(key):
                await await_fn(key)
