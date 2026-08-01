"""SyncExecutor — plain capability class owning the dedicated thread pool for sync user code.

This module owns the InterruptibleThreadPoolExecutor used by TaskBucket.run_in_thread for
all sync user code (handlers, jobs, App sync lifecycle hooks). Framework-internal
asyncio.to_thread calls (logging, database) are NOT routed here — they continue using
the loop-default executor.

SyncExecutor is a plain class (no Resource/Service base), following the Router
(hassette.bus.router) and AppRegistry (hassette.core.app_registry) precedent — it is
constructed during Hassette.__init__() before the Resource lifecycle starts, so every
TaskBucket has a working sync executor from birth. The pool is not created at
construction — rebuild_pool() is the sole pool constructor, called by
SyncExecutorService.on_initialize() on both first start and restart-in-place.

SyncExecutorService (hassette.core.sync_executor_service) wraps this capability for
lifecycle concerns: on_initialize() creates the pool via rebuild_pool(), serve() runs
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

# Pool saturation defaults — mirror command_executor's capacity-warning defaults but scoped
# to global pool saturation. Pool saturation is a global condition (not per-entity), so a
# single global timestamp is the right rate-limit model (cf. enqueue_record in command_executor).
# Both are user-configurable via lifecycle.sync_executor_saturation_warn_threshold /
# lifecycle.sync_executor_saturation_warn_rate_limit_seconds (see config/models.py); these
# module-level defaults exist only so SyncExecutor works standalone (e.g. in tests) without
# a HassetteConfig, and are what rebuild_pool() falls back to when the caller omits them.
_DEFAULT_SATURATION_WARN_THRESHOLD = 0.75
_DEFAULT_SATURATION_WARN_RATE_LIMIT_SECS = 30.0

# Probe cadence — how often serve() reads pool occupancy when there are no new submissions.
# This is the "8/8 workers stuck" detection signal: a submission-only check goes silent
# exactly when the pool is fully starved, so the probe fires regardless of submission rate.
# Fixed (not user-configurable): keeping it >= the *default* rate-limit window prevents
# self-suppression at default settings. Raising the configured rate-limit window above this
# probe interval doesn't silence the probe — it just aligns probe-triggered warnings to the
# rate-limit cadence instead of the probe cadence.
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

    The pool is not created at construction — ``rebuild_pool()`` is the sole pool constructor,
    called by ``SyncExecutorService.on_initialize()`` on both first start and restart-in-place.
    ``shutdown_pool()`` tears it down within a budgeted timeout.
    """

    executor: InterruptibleThreadPoolExecutor | None
    """The dedicated thread-pool executor for all sync user code. None until rebuild_pool()."""

    _outstanding_submissions: int
    """Count of futures submitted but not yet completed (loop-thread-only, no lock needed)."""

    _last_saturation_warn_ts: float | None
    """Monotonic timestamp of the last pool-saturation WARNING, or None if no warning has fired yet."""

    saturation_warn_threshold: float
    """Occupancy fraction (0-1) above which log_saturation_rate_limited() warns.
    Set by rebuild_pool(), sourced from lifecycle.sync_executor_saturation_warn_threshold."""

    saturation_warn_rate_limit_seconds: float
    """Minimum seconds between repeated saturation WARNINGs. Set by rebuild_pool(), sourced
    from lifecycle.sync_executor_saturation_warn_rate_limit_seconds."""

    def __init__(self) -> None:
        self.executor = None
        self._outstanding_submissions = 0
        self._last_saturation_warn_ts = None
        self.saturation_warn_threshold = _DEFAULT_SATURATION_WARN_THRESHOLD
        self.saturation_warn_rate_limit_seconds = _DEFAULT_SATURATION_WARN_RATE_LIMIT_SECS
        self.logger = getLogger(f"{__name__}.SyncExecutor")

    def rebuild_pool(
        self,
        max_workers: int,
        thread_name_prefix: str = SYNC_EXECUTOR_THREAD_NAME_PREFIX,
        saturation_warn_threshold: float = _DEFAULT_SATURATION_WARN_THRESHOLD,
        saturation_warn_rate_limit_seconds: float = _DEFAULT_SATURATION_WARN_RATE_LIMIT_SECS,
    ) -> None:
        """Create a fresh thread pool and reset saturation state.

        Sole pool constructor — called by ``SyncExecutorService.on_initialize()`` on both
        first start and restart-in-place. Does not shut down any existing pool; the caller
        always calls ``shutdown_pool()`` before re-initializing on restart.

        Args:
            max_workers: Maximum number of worker threads for the new pool.
            thread_name_prefix: Prefix applied to spawned worker thread names.
            saturation_warn_threshold: Occupancy fraction (0-1) above which a saturation
                WARNING is logged. Defaults to lifecycle.sync_executor_saturation_warn_threshold's
                default value.
            saturation_warn_rate_limit_seconds: Minimum seconds between repeated saturation
                WARNINGs. Defaults to lifecycle.sync_executor_saturation_warn_rate_limit_seconds's
                default value.
        """
        self.executor = InterruptibleThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=thread_name_prefix,
        )
        self._outstanding_submissions = 0
        self._last_saturation_warn_ts = None
        self.saturation_warn_threshold = saturation_warn_threshold
        self.saturation_warn_rate_limit_seconds = saturation_warn_rate_limit_seconds

    def shutdown_pool(self, timeout: float) -> None:
        """Shut down the thread pool within the given join/interrupt budget.

        Args:
            timeout: Total seconds budgeted for the join/interrupt loop.
        """
        if self.executor is not None:
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

        Raises:
            RuntimeError: If the pool has not been created via ``rebuild_pool()``.
        """
        if self.executor is None:
            raise RuntimeError("SyncExecutor.submit() called before rebuild_pool() — no pool available")
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
        """Track an outstanding submission: increment counter and decrement via done-callback.

        Both the increment (called on the event loop thread, immediately after
        run_in_executor returns) and the done-callback decrement (delivered to the
        event loop thread when the future resolves) run on the same thread, so
        no lock is needed.

        Args:
            future: The asyncio.Future returned by loop.run_in_executor.
        """
        self._outstanding_submissions += 1

        def _on_done(_f: "asyncio.Future[Any]") -> None:
            self._outstanding_submissions = max(0, self._outstanding_submissions - 1)

        future.add_done_callback(_on_done)
        self.log_saturation_rate_limited()

    def log_saturation_rate_limited(self) -> None:
        """Emit a pool-saturation WARNING when outstanding submissions cross the configured
        threshold, rate-limited.

        Uses a single global timestamp for rate-limiting — pool saturation is a global
        condition, not per-entity, so the global-timestamp model from enqueue_record
        (command_executor.py) is the right fit here (not the per-entity dict in
        log_timeout_rate_limited).

        Outstanding-submission count is tracked via a dedicated counter incremented on
        submission and decremented in the future's done-callback. Both operations run on
        the event loop thread, so the counter needs no lock. The queue depth is read for
        log context only — it does not gate the warning.

        Threshold and rate-limit are set by rebuild_pool() (sourced from
        lifecycle.sync_executor_saturation_warn_threshold /
        lifecycle.sync_executor_saturation_warn_rate_limit_seconds), not read here directly —
        SyncExecutor is a plain capability class with no ``hassette`` reference.
        """
        if self.executor is None:
            return
        max_workers: int = self.executor._max_workers  # pyright: ignore[reportAttributeAccessIssue]

        occupancy = self._outstanding_submissions / max_workers
        if occupancy < self.saturation_warn_threshold:
            return  # below threshold — nothing to warn about

        now = time.monotonic()
        if (
            self._last_saturation_warn_ts is not None
            and now - self._last_saturation_warn_ts < self.saturation_warn_rate_limit_seconds
        ):
            return  # rate-limited — suppress until window expires
        self._last_saturation_warn_ts = now

        # Read queue depth for context only — not a gating condition.
        # _work_queue is a SimpleQueue; qsize() is accurate under the GIL.
        queue_depth: int = self.executor._work_queue.qsize()  # pyright: ignore[reportAttributeAccessIssue]

        self.logger.warning(
            "Sync-handler pool approaching saturation: ~%d/%d outstanding submissions, %d queued "
            "— consider raising lifecycle.sync_executor_max_workers or async-ifying slow handlers",
            self._outstanding_submissions,
            max_workers,
            queue_depth,
        )
