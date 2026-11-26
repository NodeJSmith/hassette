"""SyncExecutorService — lifecycle wrapper around the SyncExecutor thread-pool capability.

The thread pool used by TaskBucket.run_in_thread for all sync user code (handlers, jobs,
App sync lifecycle hooks) is owned by SyncExecutor (hassette.core.sync_executor) — a plain
capability class constructed in Hassette.__init__() before the Resource lifecycle starts, so
every TaskBucket holds a SyncExecutor reference from birth. The pool does not exist yet at that
point: submit() raises until on_initialize() has built it. This service wraps that capability
for Resource/Service lifecycle concerns only: on_initialize() creates the pool (on every
initialization, including a same-instance re-initialization), serve() runs the periodic saturation probe, and
on_shutdown() tears the pool down within its configured budget.

Shutdown ordering is declarative: BusService, SchedulerService, and AppHandler all
declare depends_on=[SyncExecutorService], so wave-based shutdown tears them down
*before* this service.  The pool's shutdown hook therefore runs only after every
component that can submit sync work has already stopped — closing the race where an
AppSync hook submits to a closed pool and raises RuntimeError.
"""

import asyncio
from typing import TYPE_CHECKING, ClassVar

from hassette.config.models import SYNC_EXECUTOR_JOIN_TIMEOUT_SECONDS
from hassette.core.sync_executor import _SATURATION_PROBE_INTERVAL_SECS, SYNC_EXECUTOR_THREAD_NAME_PREFIX
from hassette.resources.base import Resource
from hassette.resources.lifecycle import mark_ready
from hassette.resources.service import Service
from hassette.resources.shutdown_deadline import clamp_to_shutdown_deadline

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.core.sync_executor import SyncExecutor


class SyncExecutorService(Service):
    """Lifecycle wrapper around the SyncExecutor thread-pool capability.

    Wraps the SyncExecutor built in Hassette.__init__() for Resource/Service lifecycle
    concerns: on_initialize() creates the pool (first start and re-initialization alike),
    serve() runs the periodic saturation probe, and on_shutdown() tears the pool down.
    Consumers (BusService, SchedulerService, AppHandler) declare
    depends_on=[SyncExecutorService] and wait for readiness, so no consumer can submit
    work before the pool exists.

    SyncExecutorService declares depends_on=[] (it needs no DB or other service).
    Wave-based shutdown tears consumers down before this service.
    """

    depends_on: ClassVar[list[type[Resource]]] = []
    required: ClassVar[bool] = True
    shutdown_hook_timeout_applies: ClassVar[bool] = False
    """A foundation service: the root's foundation stage bounds its shutdown, and its join has a fixed cap."""

    sync_executor: "SyncExecutor"
    """The SyncExecutor capability instance whose lifecycle this service manages."""

    def __init__(self, hassette: "Hassette", *, parent: Resource | None = None) -> None:
        super().__init__(hassette, parent=parent)
        self.sync_executor = hassette.sync_executor

    async def on_initialize(self) -> None:
        """Create the thread pool — covers both initial start and a same-instance re-initialization."""
        lifecycle = self.hassette.config.lifecycle
        self.sync_executor.rebuild_pool(
            lifecycle.sync_executor_max_workers,
            SYNC_EXECUTOR_THREAD_NAME_PREFIX,
            saturation_warn_threshold=lifecycle.sync_executor_saturation_warn_threshold,
            saturation_warn_rate_limit_seconds=lifecycle.sync_executor_saturation_warn_rate_limit_seconds,
        )

    async def serve(self) -> None:
        """Mark ready, then probe pool occupancy every ``_SATURATION_PROBE_INTERVAL_SECS`` until shutdown.

        See that constant in ``sync_executor.py`` for the cadence rationale.
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
                return
            except TimeoutError:
                self.sync_executor.log_saturation_rate_limited()

    async def on_shutdown(self) -> None:
        """Shut down the thread pool within ``SYNC_EXECUTOR_JOIN_TIMEOUT_SECONDS``, clamped to the shutdown deadline.

        Called by Service.shutdown() after the serve task has been cancelled, so no new
        work can be submitted by the time this runs. ``shutdown_pool`` is a blocking
        call (it joins/interrupts worker threads), so it runs in a worker thread via
        ``asyncio.to_thread`` to avoid parking the event loop. The join budget is a fixed part of
        the foundation stage's budget (``FOUNDATION_SHUTDOWN_BUDGET_SECONDS``); threads that survive
        it are reported by ``SyncExecutor.surviving_threads()``, which the root reads after this stage.
        """
        budget = clamp_to_shutdown_deadline(self, SYNC_EXECUTOR_JOIN_TIMEOUT_SECONDS)
        self.logger.debug("Shutting down SyncExecutorService executor (budget=%.1fs)", budget)
        await asyncio.to_thread(self.sync_executor.shutdown_pool, budget)
        self.logger.debug("SyncExecutorService executor shut down")
