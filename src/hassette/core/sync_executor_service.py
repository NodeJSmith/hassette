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
import typing
from typing import ClassVar

from hassette.resources.base import Resource
from hassette.resources.restart import RestartSpec
from hassette.resources.service import Service
from hassette.task_bucket.interruptible_executor import InterruptibleThreadPoolExecutor
from hassette.types.enums import RestartType

if typing.TYPE_CHECKING:
    from hassette import Hassette


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

    def __init__(self, hassette: "Hassette", *, parent: Resource | None = None) -> None:
        super().__init__(hassette, parent=parent)
        # Construct immediately — no None window before serve() runs.
        self.executor = InterruptibleThreadPoolExecutor(
            max_workers=hassette.config.lifecycle.sync_executor_max_workers,
            thread_name_prefix="hassette-sync",
        )

    async def serve(self) -> None:
        """Mark ready and idle until shutdown.

        T05 EXTENSION POINT: replace the single ``shutdown_event.wait()`` below with the
        periodic saturation probe — a ``while not shutdown_event.is_set()`` loop that
        reads the active worker count from ``self.executor`` every ~30s (via
        ``asyncio.wait_for(self.shutdown_event.wait(), timeout=...)``) and emits a
        rate-limited WARNING when approaching the configured pool ceiling.
        """
        self.mark_ready(reason="SyncExecutorService started")
        # Park at zero cost until shutdown; no polling latency.
        await self.shutdown_event.wait()

    async def on_shutdown(self) -> None:
        """Shut down the executor within the configured interruption budget.

        Called by Service.shutdown() after the serve task has been cancelled, so no new
        work can be submitted by the time this runs.  ``executor.shutdown`` is a blocking
        call (it joins/interrupts worker threads), so it runs in a worker thread via
        ``asyncio.to_thread`` to avoid parking the event loop while other services in the
        shutdown wave finish.  The budget is capped at ``resource_shutdown_timeout_seconds``
        — the per-wave bound on how long this hook may run — so the join/interrupt phase
        cannot push the wave (and thus the total shutdown) past its budget.
        """
        lifecycle = self.hassette.config.lifecycle
        budget = min(
            lifecycle.sync_executor_shutdown_timeout_seconds,
            float(lifecycle.resource_shutdown_timeout_seconds),
        )
        self.logger.debug("Shutting down SyncExecutorService executor (budget=%.1fs)", budget)
        await asyncio.to_thread(self.executor.shutdown, timeout=budget)
        self.logger.debug("SyncExecutorService executor shut down")
