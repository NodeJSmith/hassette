"""Module-level write-queue plumbing for ``DatabaseService``.

These functions replace methods that previously lived on ``DatabaseService`` — the write-queue
worker loop, its teardown handoff, and the error it raises once torn down. They accept the
service as their first argument instead of being bound methods, the same shape
``hassette.core.execution_pipeline``'s functions take ``executor: "CommandExecutor"``. None of
them are called from outside ``database_service.py`` in application code (aside from direct
unit-test imports), so moving them here changes no production call site.
"""

import asyncio
import typing
from collections.abc import Coroutine
from typing import Any

from hassette.exceptions import WriteQueueUnavailableError

if typing.TYPE_CHECKING:
    from hassette.core.database_service import DatabaseService

_WriteQueueItem = tuple[Coroutine[Any, Any, Any], "asyncio.Future[Any] | None"]
"""Type alias for items placed on the DB write queue."""


async def run_write_queue_worker(service: "DatabaseService") -> None:
    """Drain ``service._db_write_queue`` sequentially.

    Each item is a (coroutine, future) pair. If future is not None, the
    coroutine's result (or exception) is delivered through it. If future is
    None, any exception is logged and the worker continues.

    The loop runs until cancelled by ``on_shutdown()``.
    """
    if service._db_write_queue is None:
        raise RuntimeError("run_write_queue_worker() started before on_initialize() set _db_write_queue")
    queue = service._db_write_queue
    while True:
        coro, future = await queue.get()
        if future is not None and future.cancelled():
            # The submit() caller timed out or was cancelled while this write was still
            # queued; it has already reported the write as not done, so it must not run.
            service.logger.debug("Skipping withdrawn DB write %s", coro.__qualname__)
            coro.close()
            queue.task_done()
            continue
        service._executing_future = future
        try:
            result = await coro
            if future is not None and not future.done():
                future.set_result(result)
        except asyncio.CancelledError:
            # on_shutdown() bounds its drain, so the worker can be cancelled with an item
            # still executing. close_remaining_queue_items() only reaches items still on
            # the queue, so without this the submit() caller awaiting this future would
            # stay suspended forever.
            if future is not None and not future.done():
                future.cancel()
            raise
        except Exception as exc:
            if future is not None and not future.done():
                future.set_exception(exc)
            else:
                service.logger.exception("Unhandled error in enqueued DB write")
        finally:
            service._executing_future = None
            queue.task_done()


def log_worker_exit(service: "DatabaseService", task: "asyncio.Task[None]") -> None:
    """Log an unhandled exception from ``service._db_worker_task``.

    ``_db_worker_task`` bypasses TaskBucket entirely (see ``DatabaseService.on_initialize()``),
    so ``TaskBucket.add()``'s own done callback -- the only other place a worker crash gets
    logged and forwarded to the installed exception recorders -- never runs for it. Without
    this callback, a worker crash (e.g. the ``RuntimeError`` guard in
    ``run_write_queue_worker()`` when ``_db_write_queue`` is ``None``, or a ``ValueError`` from
    ``queue.task_done()``) would go completely unlogged, and every later ``submit()`` would sit
    out its full queue timeout awaiting a future no worker will ever resolve.
    """
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        service.logger.error("DB write worker for %s exited unexpectedly", service.unique_name, exc_info=exc)


def detach_write_queue(service: "DatabaseService") -> "asyncio.Queue[_WriteQueueItem] | None":
    """Take the write queue away so ``submit()``/``enqueue()`` start rejecting, and return it.

    Both teardown paths (``on_shutdown()``, ``_force_terminal()``) go through here so the
    detach and the ``_write_queue_detached`` flag that records it can never drift apart — see
    ``build_queue_unavailable_error()`` for what that flag buys. The flag is only raised when
    there was a queue to take, so tearing down a service whose ``on_initialize()`` never got far
    enough to create one still reports the pre-init cause.
    """
    queue, service._db_write_queue = service._db_write_queue, None
    if queue is not None:
        service._write_queue_detached = True
    return queue


def build_queue_unavailable_error(service: "DatabaseService", method: str) -> WriteQueueUnavailableError:
    """Build the rejection raised when ``service._db_write_queue`` is gone.

    The queue is ``None`` both before ``on_initialize()`` creates it and after a teardown
    path detaches it, so the message comes from ``_write_queue_detached`` -- the flag
    ``detach_write_queue()`` sets -- rather than from the resource's status. Status cannot
    answer this: an ``on_initialize()`` failure before the queue is created leaves the
    service in ``FAILED``/``CRASHED`` with no teardown having run, which would otherwise be
    reported as a post-shutdown call.
    """
    if service._write_queue_detached:
        return WriteQueueUnavailableError(f"DatabaseService.{method}() called after shutdown")
    return WriteQueueUnavailableError(f"DatabaseService.{method}() called before on_initialize()")
