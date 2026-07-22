"""SyncExecutorService — lifecycle wrapper around the SyncExecutor thread-pool capability.

The thread pool used by TaskBucket.run_in_thread for all sync user code (handlers, jobs,
App sync lifecycle hooks) is owned by SyncExecutor (hassette.core.sync_executor) — a plain
capability class constructed in Hassette.__init__() before the Resource lifecycle starts, so
every TaskBucket has a working sync executor from birth. This service wraps that capability
for Resource/Service lifecycle concerns only: on_initialize() creates the pool (covering both
initial start and restart-in-place), serve() runs the periodic saturation probe, and
on_shutdown() tears the pool down within its configured budget.

Shutdown ordering is declarative: BusService, SchedulerService, and AppHandler all
declare depends_on=[SyncExecutorService], so wave-based shutdown tears them down
*before* this service.  The pool's shutdown hook therefore runs only after every
component that can submit sync work has already stopped — closing the race where an
AppSync hook submits to a closed pool and raises RuntimeError.
"""

import asyncio
from typing import TYPE_CHECKING, ClassVar

from hassette.core.sync_executor import _SATURATION_PROBE_INTERVAL_SECS, SYNC_EXECUTOR_THREAD_NAME_PREFIX
from hassette.resources.base import Resource
from hassette.resources.lifecycle import mark_ready
from hassette.resources.restart import CORE_PERMANENT_RESTART
from hassette.resources.service import Service

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.core.sync_executor import SyncExecutor


class SyncExecutorService(Service):
    """Lifecycle wrapper around the SyncExecutor thread-pool capability.

    Wraps the SyncExecutor built in Hassette.__init__() for Resource/Service lifecycle
    concerns: on_initialize() creates the pool (first start and restart-in-place alike),
    serve() runs the periodic saturation probe, and on_shutdown() tears the pool down.
    Consumers (BusService, SchedulerService, AppHandler) declare
    depends_on=[SyncExecutorService] and wait for readiness, so no consumer can submit
    work before the pool exists.

    SyncExecutorService declares depends_on=[] (it needs no DB or other service).
    Wave-based shutdown tears consumers down before this service.
    """

    depends_on: ClassVar[list[type[Resource]]] = []
    restart_spec = CORE_PERMANENT_RESTART

    sync_executor: "SyncExecutor"
    """The SyncExecutor capability instance whose lifecycle this service manages."""

    def __init__(self, hassette: "Hassette", *, parent: Resource | None = None) -> None:
        super().__init__(hassette, parent=parent)
        self.sync_executor = hassette.sync_executor

    async def on_initialize(self) -> None:
        """Create the thread pool — covers both initial start and restart-in-place."""
        self.sync_executor.rebuild_pool(
            self.hassette.config.lifecycle.sync_executor_max_workers,
            SYNC_EXECUTOR_THREAD_NAME_PREFIX,
        )

    async def serve(self) -> None:
        """Mark ready, then probe pool occupancy every ~30s until shutdown.

        The periodic probe is the "8/8 workers stuck" signal: a submission-time check
        alone goes silent exactly when the pool is fully starved (no new submissions
        arrive when all workers are blocked).  The probe fires regardless of submission
        rate so the operator still sees the WARNING at the configured cadence.

        Probe cadence (_SATURATION_PROBE_INTERVAL_SECS) is set equal to the rate-limit
        suppress window — see the module-level constant comments in sync_executor.py
        for the coupling invariant (shortening the probe interval below the suppress
        window causes self-suppression).
        """
        mark_ready(self, reason="SyncExecutorService started")
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
                self.sync_executor.log_saturation_rate_limited()

    async def on_shutdown(self) -> None:
        """Shut down the thread pool within the configured interruption budget.

        Called by Service.shutdown() after the serve task has been cancelled, so no new
        work can be submitted by the time this runs. ``shutdown_pool`` is a blocking
        call (it joins/interrupts worker threads), so it runs in a worker thread via
        ``asyncio.to_thread`` to avoid parking the event loop while other services in the
        shutdown wave finish. The budget is capped at ``resource_shutdown_timeout_seconds``
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
        await asyncio.to_thread(self.sync_executor.shutdown_pool, budget)
        self.logger.debug("SyncExecutorService executor shut down")
