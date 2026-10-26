"""Write-queue plumbing for ``DatabaseService``.

The worker loop, its teardown handoff, and the error raised once the queue is torn down are
module-level functions that take the service as their first argument, the same shape
``hassette.core.execution_pipeline``'s functions take ``executor: "CommandExecutor"``. The
queue-facing methods callers reach through the service -- ``submit()``, ``enqueue()``, and the
shutdown drain/close pair -- live on ``DatabaseWriteQueueMixin``, which ``DatabaseService``
inherits.
"""

import asyncio
import typing
from collections.abc import Callable, Coroutine
from typing import Any

from hassette.core.pipeline_counters import PipelineCounter
from hassette.exceptions import WriteQueueUnavailableError

if typing.TYPE_CHECKING:
    import logging

    import aiosqlite

    from hassette import Hassette
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
            service._write_progress_count += 1
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
        except Exception as exc:  # broad on purpose: runs caller-supplied coroutines, whose errors belong to the caller
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


def build_queue_unavailable_error(service: "DatabaseWriteQueueMixin", method: str) -> WriteQueueUnavailableError:
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


class DatabaseWriteQueueMixin:
    """Write-queue methods of ``DatabaseService``; reads the host attributes declared below."""

    hassette: "Hassette"
    logger: "logging.Logger"
    _db: "aiosqlite.Connection | None"
    _db_write_queue: "asyncio.Queue[_WriteQueueItem] | None"
    _executing_future: "asyncio.Future[Any] | None"
    _write_queue_detached: bool
    _write_progress_count: int
    _waiting_submits: int
    """``submit()`` callers currently suspended waiting for queue capacity; ``enqueue()`` yields to them."""

    async def drain_write_queue(self, queue: asyncio.Queue[_WriteQueueItem], timeout: float) -> None:
        """Wait for already-queued writes to finish, bounded by ``timeout``.

        A dead worker (nobody left to call task_done()) or a wedged one (stuck mid-write) never
        lets ``queue.join()`` complete on its own. Left unbounded it would use up the foundation
        stage's budget and leave the connections unclosed.

        Args:
            queue: The write queue to drain. Already detached from ``_db_write_queue``, so no new
                items can arrive while this waits.
            timeout: The drain's bound: ``SHUTDOWN_DRAIN_TIMEOUT_SECONDS``, one of the foundation budget's
                fixed parts, clamped to what is left of the shutdown deadline.
        """
        try:
            async with asyncio.timeout(timeout):
                await queue.join()
        except TimeoutError:
            # qsize() excludes the item the worker already dequeued, which the caller's cancel()
            # abandons too — so it is a floor, not the total.
            self.logger.warning(
                "Write queue did not drain within %.2fs — abandoning %d queued write(s) "
                "plus any write already in flight",
                timeout,
                queue.qsize(),
            )

    def close_remaining_queue_items(self, queue: asyncio.Queue[_WriteQueueItem] | None) -> None:
        """Close any coroutines left on the write queue without executing them.

        Called during shutdown to prevent unawaited-coroutine warnings from GC.
        """
        if queue is None:
            return
        closed = 0
        while True:
            try:
                coro, future = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            coro.close()
            if future is not None and not future.done():
                future.cancel()
            queue.task_done()
            closed += 1
        if closed:
            self.logger.debug("Closed %d remaining coroutine(s) from write queue during shutdown", closed)

    async def submit(self, coro: Coroutine[Any, Any, Any]) -> Any:
        """Submit a coroutine for serialized execution and await its result.

        The coroutine is placed on the write queue and executed by the single-writer
        worker. The caller is suspended until the coroutine completes.

        One ``DatabaseConfig.write_submit_timeout_seconds`` deadline bounds the entire wait to
        start: waiting for queue capacity (the queue is bounded -- see ``write_queue_max``) and
        waiting for the worker to dequeue and start the write both draw from it. If it expires
        first, the write is withdrawn (or, if it never fit on the queue, simply closed) and
        ``TimeoutError`` is raised, so the caller may safely retry it. Once the worker has
        started the write it is awaited to completion, because it may commit; a caller that must
        also bound a wedged in-progress write (see ``update_heartbeat()``) wraps this call in its
        own timeout.

        Args:
            coro: The coroutine to execute.

        Returns:
            The return value of the coroutine.

        Raises:
            TimeoutError: The write never started before the timeout expired.
            Exception: Whatever exception the coroutine raises.
        """
        if (queue := self._db_write_queue) is None:  # captured once -- enqueue() has no await, needs no capture
            coro.close()
            raise build_queue_unavailable_error(self, "submit")
        timeout = self.hassette.config.database.write_submit_timeout_seconds
        # Shared deadline: the queue.put() below and the worker-start wait further down both
        # draw from it, so together they never exceed one write_submit_timeout_seconds wait.
        deadline = asyncio.get_running_loop().time() + timeout
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        # Counted for the whole put so enqueue() can't take the slot the worker frees for this
        # caller: asyncio wakes a waiting putter on a later loop tick, and a put_nowait() that
        # runs first would otherwise win the slot every time under a fire-and-forget storm.
        self._waiting_submits += 1
        try:
            # asyncio.timeout, not wait_for: the session finalize submits after the TaskBucket seal
            # (see "No implicit task creation at exit" in .claude/rules/resource-lifecycle.md)
            async with asyncio.timeout(timeout):
                await queue.put((coro, future))
        except TimeoutError:
            coro.close()
            future.cancel()
            raise TimeoutError(f"DB write queue full after {timeout}s — never enqueued") from None
        except BaseException:
            coro.close()
            future.cancel()
            raise
        finally:
            self._waiting_submits -= 1
        remaining = max(0.0, deadline - asyncio.get_running_loop().time())
        try:
            # asyncio.wait, unlike wait_for, never cancels the future on timeout, so a write that
            # has already started is left running for the await below.
            await asyncio.wait((future,), timeout=remaining)
        except asyncio.CancelledError:
            future.cancel()
            raise
        timed_out = not future.done()
        # Race-free only because run_write_queue_worker() sets _executing_future with no await
        # between dequeuing an item and starting it: a future that is not _executing_future here
        # has definitely not started, and cancelling it makes the worker skip it.
        not_started = future is not self._executing_future
        if timed_out and not_started:
            future.cancel()
            raise TimeoutError(f"DB write still queued after {timeout}s — withdrawn without running")
        return await future

    def enqueue(self, coro: Coroutine[Any, Any, Any]) -> bool:
        """Submit a coroutine for fire-and-forget execution.

        Returns immediately. The coroutine is placed on the write queue and
        executed by the single-writer worker. Any exception is logged; the worker
        continues processing subsequent items.

        While any ``submit()`` caller is waiting for queue capacity, the item is dropped and
        counted under ``PipelineCounter.DB_WRITE_QUEUE_YIELDED_TO_SUBMIT`` instead, so an awaited
        write always gets the next free slot.

        Args:
            coro: The coroutine to execute.

        Returns:
            True if enqueued successfully, False if dropped due to a full queue or a waiting ``submit()``.
        """
        if self._db_write_queue is None:  # sync method, no await point -- see submit()'s capture-once comment
            coro.close()
            raise build_queue_unavailable_error(self, "enqueue")
        if self._waiting_submits > 0:
            coro.close()
            self.hassette.pipeline_counters.increment(PipelineCounter.DB_WRITE_QUEUE_YIELDED_TO_SUBMIT)
            # DEBUG, not ERROR like the full-queue drop: these drops come in storms, and an ERROR
            # record would itself be persisted through this queue. The counter is the signal.
            self.logger.debug(
                "Dropping fire-and-forget DB write while %d submit() caller(s) wait", self._waiting_submits
            )
            return False
        try:
            self._db_write_queue.put_nowait((coro, None))
        except asyncio.QueueFull:
            coro.close()
            self.logger.error(
                "DB write queue full (%d items) — dropping fire-and-forget task",
                self._db_write_queue.qsize(),
            )
            return False
        qsize = self._db_write_queue.qsize()
        if qsize > 0 and qsize % 100 == 0:
            self.logger.warning("DB write queue depth at %d items — potential backlog", qsize)
        return True

    def enqueue_if_ready(self, make_coro: Callable[[], Coroutine[Any, Any, Any]]) -> bool:
        """Enqueue ``make_coro()`` if the database and write queue are up; False if dropped.

        Takes a factory rather than a coroutine so nothing is created (and left unawaited)
        when the database is not ready.
        """
        if self._db is None or self._db_write_queue is None:
            return False
        return self.enqueue(make_coro())
