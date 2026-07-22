"""SyncExecutor — plain capability class owning the dedicated thread pool for sync user code.

This module owns the InterruptibleThreadPoolExecutor used by TaskBucket.run_in_thread for
all sync user code (handlers, jobs, App sync lifecycle hooks). Framework-internal
asyncio.to_thread calls (logging, database) are NOT routed here — they continue using
the loop-default executor.

SyncExecutor is a plain class (no Resource/Service base), following the Router
(hassette.bus.router) and AppRegistry (hassette.core.app_registry) precedent — it is
constructed during Hassette.__init__() before the Resource lifecycle starts, so every
TaskBucket has a working sync executor from birth.

SyncExecutorService (hassette.core.sync_executor_service) wraps this capability for
lifecycle concerns: on_initialize() rebuilds the pool via rebuild_pool(), serve() runs
the saturation probe loop, and on_shutdown() tears the pool down via shutdown_pool().
"""

import asyncio
import threading
import time
from contextvars import ContextVar, copy_context
from dataclasses import dataclass
from logging import getLogger
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar, cast

from hassette.task_bucket.interruptible_executor import InterruptibleThreadPoolExecutor

if TYPE_CHECKING:
    from collections.abc import Callable

P = ParamSpec("P")
R = TypeVar("R")

# Pool saturation constants — mirror command_executor._CAPACITY_WARN_THRESHOLD /
# _CAPACITY_WARN_RATE_LIMIT_SECS but scoped to global pool saturation.
# Pool saturation is a global condition (not per-entity), so a single global
# timestamp is the right rate-limit model (cf. enqueue_record in command_executor).
_SATURATION_WARN_THRESHOLD = 0.75

# Suppression window: rate-limit repeated saturation WARNINGs to at most once per
# this many seconds.  The periodic probe fires every _SATURATION_PROBE_INTERVAL_SECS;
# keeping the probe interval >= this window ensures the probe does NOT self-suppress —
# i.e. the probe always has a chance to fire even when submissions have stopped.
# WARNING: if you shorten _SATURATION_PROBE_INTERVAL_SECS below _SATURATION_WARN_RATE_LIMIT_SECS
# the probe will silently suppress itself and operators will see no signal during total
# pool starvation.  Keep probe interval >= suppress window.
_SATURATION_WARN_RATE_LIMIT_SECS = 30.0

# Probe cadence — how often serve() reads pool occupancy when there are no new submissions.
# This is the "8/8 workers stuck" detection signal: a submission-only check goes silent
# exactly when the pool is fully starved, so the probe fires regardless of submission rate.
# Must be >= _SATURATION_WARN_RATE_LIMIT_SECS to avoid self-suppression (see above).
_SATURATION_PROBE_INTERVAL_SECS = 30.0

# Worker thread name prefix for the dedicated sync-user-code pool. Shared with the test
# mock executor so pool-identity assertions match production threads.
SYNC_EXECUTOR_THREAD_NAME_PREFIX = "hassette-sync"


@dataclass
class SyncWorkerHandle:
    """Shared handle between the loop thread and a sync worker for thread-identity tracking.

    Created by ``submit()`` on the loop thread and stored in ``SYNC_WORKER_HANDLE``.
    The worker thread sets ``handle.thread`` and ``handle.active`` via closure;
    ``_execute`` in ``command_executor`` reads both at the timeout site — ``active``
    distinguishes a genuinely leaked thread from a pool thread that finished the
    submitted fn but remains alive between jobs.
    """

    thread: threading.Thread | None = None
    active: bool = False
    """True while ``fn`` is executing on the worker thread; False before and after."""


SYNC_WORKER_HANDLE: ContextVar[SyncWorkerHandle | None] = ContextVar("sync_worker_handle", default=None)
"""Carries the worker handle for the current sync submission from the loop thread to _execute.

Set on the loop thread in ``submit()`` immediately after creating the handle.
``_execute`` (same asyncio task, same context snapshot) reads this ContextVar to check
``handle.thread.is_alive()`` at the timeout site.

The worker accesses the handle via closure, not via this ContextVar.  The ContextVar exists so
that ``_execute`` (running on the loop thread, in the same asyncio task) can read back the
handle reference.
"""


class SyncExecutor:
    """Plain capability class that owns the dedicated thread-pool executor for sync user code.

    Follows the Router (``hassette.bus.router``) / AppRegistry (``hassette.core.app_registry``)
    pattern — no ``Resource``/``Service`` base class, no ``hassette`` parameter, no lifecycle
    hooks. This is what makes it constructable during ``Hassette.__init__()`` before the
    Resource lifecycle starts, so every ``TaskBucket`` has a working sync executor from birth.

    ``rebuild_pool()`` and ``shutdown_pool()`` exist for lifecycle delegation — callers that
    need pool-rebuild-on-restart or budgeted teardown (``SyncExecutorService``) call these
    rather than reaching into ``executor`` directly.
    """

    executor: InterruptibleThreadPoolExecutor
    """The dedicated thread-pool executor for all sync user code."""

    _active_workers: int
    """Count of futures currently running on the executor (loop-thread-only, no lock needed)."""

    _last_saturation_warn_ts: float
    """Monotonic timestamp of the last pool-saturation WARNING (global rate-limit)."""

    def __init__(self, max_workers: int, thread_name_prefix: str = SYNC_EXECUTOR_THREAD_NAME_PREFIX) -> None:
        self.executor = InterruptibleThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=thread_name_prefix,
        )
        self._active_workers = 0
        self._last_saturation_warn_ts = 0.0
        self.logger = getLogger(f"{__name__}.SyncExecutor")

    def rebuild_pool(self, max_workers: int, thread_name_prefix: str = SYNC_EXECUTOR_THREAD_NAME_PREFIX) -> None:
        """Create a fresh thread pool and reset saturation state, for restart-in-place.

        Does not shut down any existing pool — the caller (``SyncExecutorService.on_initialize()``
        via ``restart()`` in ``resources/operations.py``) always calls ``shutdown()`` before
        ``initialize()``, so the old pool is already shut down by the time this runs.

        Args:
            max_workers: Maximum number of worker threads for the new pool.
            thread_name_prefix: Prefix applied to spawned worker thread names.
        """
        self.executor = InterruptibleThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=thread_name_prefix,
        )
        self._active_workers = 0
        self._last_saturation_warn_ts = 0.0

    def shutdown_pool(self, timeout: float) -> None:
        """Shut down the thread pool within the given join/interrupt budget.

        Args:
            timeout: Total seconds budgeted for the join/interrupt loop.
        """
        self.executor.shutdown(timeout=timeout)

    def submit(self, fn: "Callable[P, R]", *args: "P.args", **kwargs: "P.kwargs") -> "asyncio.Future[R]":
        """Submit a sync function to the dedicated executor with context propagation.

        Captures the calling thread's contextvars, wraps them into the worker call,
        and tracks the submission for pool-saturation monitoring.

        Args:
            fn: The synchronous function to run.
            *args: Positional arguments to pass to the function.
            **kwargs: Keyword arguments to pass to the function.

        Returns:
            An :class:`asyncio.Future` that resolves to the return value of *fn*.
        """
        parent_ctx = copy_context()
        handle = SyncWorkerHandle()
        SYNC_WORKER_HANDLE.set(handle)

        def _call() -> R:
            handle.thread = threading.current_thread()
            handle.active = True
            try:
                return parent_ctx.run(fn, *args, **kwargs)
            finally:
                handle.active = False

        loop = asyncio.get_running_loop()
        future: asyncio.Future[R] = loop.run_in_executor(self.executor, _call)
        self.track_submission(cast("asyncio.Future[Any]", future))
        return future

    def track_submission(self, future: "asyncio.Future[Any]") -> None:
        """Track an active submission: increment counter and decrement via done-callback.

        Both the increment (called on the event loop thread, immediately after
        run_in_executor returns) and the done-callback decrement (delivered to the
        event loop thread when the future resolves) run on the same thread, so
        no lock is needed.

        Args:
            future: The asyncio.Future returned by loop.run_in_executor.
        """
        self._active_workers += 1

        def _on_done(_f: "asyncio.Future[Any]") -> None:
            # run_in_executor done callbacks fire on the event loop thread.
            self._active_workers = max(0, self._active_workers - 1)

        future.add_done_callback(_on_done)
        self.log_saturation_rate_limited()

    def log_saturation_rate_limited(self) -> None:
        """Emit a pool-saturation WARNING when active workers cross ~75%, rate-limited.

        Uses a single global timestamp for rate-limiting — pool saturation is a global
        condition, not per-entity, so the global-timestamp model from enqueue_record
        (command_executor.py) is the right fit here (not the per-entity dict in
        log_timeout_rate_limited).

        Active-worker count is tracked via a dedicated counter incremented on submission
        and decremented in the future's done-callback.  Both operations run on the event
        loop thread, so the counter needs no lock.  The queue depth is read for log
        context only — it does not gate the warning.
        """
        max_workers: int = self.executor._max_workers  # pyright: ignore[reportAttributeAccessIssue]

        occupancy = self._active_workers / max_workers
        if occupancy < _SATURATION_WARN_THRESHOLD:
            return  # below threshold — nothing to warn about

        now = time.monotonic()
        if now - self._last_saturation_warn_ts < _SATURATION_WARN_RATE_LIMIT_SECS:
            return  # rate-limited — suppress until window expires
        self._last_saturation_warn_ts = now

        # Read queue depth for context only — not a gating condition.
        # _work_queue is a SimpleQueue; qsize() is accurate under the GIL.
        queue_depth: int = self.executor._work_queue.qsize()  # pyright: ignore[reportAttributeAccessIssue]

        self.logger.warning(
            "Sync-handler pool approaching saturation: ~%d/%d workers active, %d queued "
            "— consider raising lifecycle.sync_executor_max_workers or async-ifying slow handlers",
            self._active_workers,
            max_workers,
            queue_depth,
        )
