"""Loop-safety guard shared by every synchronous facade."""

import asyncio


def guard_not_in_event_loop(label: str) -> None:
    """Raise RuntimeError if called from inside a running event loop.

    Every sync facade enforces this one loop-safety contract: the cache facades
    (:class:`~hassette.cache.sync.SyncCache`, :class:`~hassette.cache.dummy.DummySyncCache`)
    call it directly, and the Api, Bus, and Scheduler facades reach it through
    :meth:`~hassette.task_bucket.task_bucket.TaskBucket.run_sync`.

    Args:
        label: Name of the sync method being called, used in the error message.

    Raises:
        RuntimeError: If an event loop is running in the current thread.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass  # not in a loop -> safe to run synchronously
    else:
        raise RuntimeError(
            f"This sync method ({label}) was called from within an event loop. Use the async method instead."
        )
