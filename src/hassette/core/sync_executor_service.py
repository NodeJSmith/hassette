"""SyncExecutorService — owns the dedicated InterruptibleThreadPoolExecutor for sync user code.

This service constructs and tears down the executor used by TaskBucket.run_in_thread
for all sync user code (handlers, jobs, App sync lifecycle hooks).  Framework-internal
asyncio.to_thread calls (logging, database) are NOT routed here — they continue using
the loop-default executor.

Shutdown ordering is declarative: BusService, SchedulerService, and AppHandler all
declare depends_on=[SyncExecutorService], so wave-based shutdown tears them down
*before* this service.  The executor's shutdown hook therefore runs only after every
component that can submit sync work has already stopped — closing the race where an
AppSync hook submits to a closed pool and raises RuntimeError.
"""

import asyncio
import time
from typing import TYPE_CHECKING, Any, ClassVar

from hassette.resources.base import Resource
from hassette.resources.restart import RestartSpec
from hassette.resources.service import Service
from hassette.task_bucket.interruptible_executor import InterruptibleThreadPoolExecutor
from hassette.types.enums import RestartType

if TYPE_CHECKING:
    from hassette import Hassette

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


class SyncExecutorService(Service):
    """Service that owns the dedicated thread-pool executor for sync user code.

    The executor is constructed in __init__ (not a startup hook). Once wire_services()
    has registered this service, hassette.sync_executor returns a live executor; before
    that the property raises RuntimeError. Constructing in __init__ avoids a None window
    on the service instance itself once it exists.

    SyncExecutorService declares depends_on=[] (it needs no DB or other service).
    Its consumers (BusService, SchedulerService, AppHandler) declare
    depends_on=[SyncExecutorService], which causes wave-based shutdown to tear
    them down before the executor.
    """

    depends_on: ClassVar[list[type[Resource]]] = []
    restart_spec: ClassVar[RestartSpec] = RestartSpec(
        restart_type=RestartType.PERMANENT,
        budget_intensity=2,
        budget_period_seconds=30,
    )

    executor: InterruptibleThreadPoolExecutor
    """The dedicated thread-pool executor for all sync user code."""

    _active_workers: int
    """Count of futures currently running on the executor (loop-thread-only, no lock needed)."""

    _last_saturation_warn_ts: float
    """Monotonic timestamp of the last pool-saturation WARNING (global rate-limit)."""

    def __init__(self, hassette: "Hassette", *, parent: Resource | None = None) -> None:
        super().__init__(hassette, parent=parent)
        # Construct immediately — no None window before serve() runs.
        self.executor = InterruptibleThreadPoolExecutor(
            max_workers=hassette.config.lifecycle.sync_executor_max_workers,
            thread_name_prefix=SYNC_EXECUTOR_THREAD_NAME_PREFIX,
        )
        self._active_workers = 0
        self._last_saturation_warn_ts = 0.0

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

    async def serve(self) -> None:
        """Mark ready, then probe pool occupancy every ~30s until shutdown.

        The periodic probe is the "8/8 workers stuck" signal: a submission-time check
        alone goes silent exactly when the pool is fully starved (no new submissions
        arrive when all workers are blocked).  The probe fires regardless of submission
        rate so the operator still sees the WARNING at the configured cadence.

        Probe cadence (_SATURATION_PROBE_INTERVAL_SECS) is set equal to the rate-limit
        suppress window (_SATURATION_WARN_RATE_LIMIT_SECS).  Shortening the probe
        interval below the suppress window would cause self-suppression — the probe
        fires but the WARNING is swallowed because the rate-limit hasn't expired.
        See module-level constant comments for the coupling invariant.
        """
        self.mark_ready(reason="SyncExecutorService started")
        while not self.shutdown_event.is_set():
            try:
                # Wait up to one probe interval for service shutdown.  We recreate
                # the coroutine on each iteration — asyncio.shield would leak an
                # orphaned inner task that keeps the event-wait alive after a
                # TimeoutError.  self.shutdown_event is the *service-level* shutdown
                # event set by request_shutdown(); the serve task is also cancelled
                # directly by Service.shutdown(), so either signal exits cleanly.
                await asyncio.wait_for(
                    self.shutdown_event.wait(),
                    timeout=_SATURATION_PROBE_INTERVAL_SECS,
                )
                # shutdown_event fired — exit the loop.
                return
            except TimeoutError:
                # Probe interval elapsed — check saturation and loop.
                self.log_saturation_rate_limited()

    async def on_shutdown(self) -> None:
        """Shut down the executor within the configured interruption budget.

        Called by Service.shutdown() after the serve task has been cancelled, so no new
        work can be submitted by the time this runs.  ``executor.shutdown`` is a blocking
        call (it joins/interrupts worker threads), so it runs in a worker thread via
        ``asyncio.to_thread`` to avoid parking the event loop while other services in the
        shutdown wave finish.  The budget is capped at ``resource_shutdown_timeout_seconds``
        — the per-wave bound on how long this hook may run — so the join/interrupt phase
        cannot push the wave (and thus the total shutdown) past its budget.

        Note: at default config the two values are equal (both 10s), so the cap is a no-op
        and the per-wave timeout is the effective backstop. Set
        ``sync_executor_shutdown_timeout_seconds`` below ``resource_shutdown_timeout_seconds``
        to give the wave explicit headroom.
        """
        lifecycle = self.hassette.config.lifecycle
        budget = min(
            lifecycle.sync_executor_shutdown_timeout_seconds,
            float(lifecycle.resource_shutdown_timeout_seconds),
        )
        self.logger.debug("Shutting down SyncExecutorService executor (budget=%.1fs)", budget)
        await asyncio.to_thread(self.executor.shutdown, timeout=budget)
        self.logger.debug("SyncExecutorService executor shut down")
