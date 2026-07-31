import asyncio
from typing import TYPE_CHECKING, ClassVar

from hassette.core.api_resource import ApiResource
from hassette.core.bus_service import BusService
from hassette.core.scheduler_service import SchedulerService
from hassette.core.state_proxy import StateProxy
from hassette.core.sync_executor_service import SyncExecutorService
from hassette.resources.base import Resource
from hassette.resources.lifecycle import mark_not_ready, mark_ready
from hassette.types.types import LOG_LEVEL_TYPE

if TYPE_CHECKING:
    from hassette import Hassette


class AppBootstrapCoordinator(Resource):
    """Own the one-time release decision for initial app bootstrap."""

    depends_on: ClassVar[list[type[Resource]]] = [
        ApiResource,
        BusService,
        SchedulerService,
        StateProxy,
        SyncExecutorService,
    ]

    def __init__(self, hassette: "Hassette", *, parent: Resource | None = None) -> None:
        super().__init__(hassette, parent=parent)
        self._released_event = asyncio.Event()
        self._bootstrap_task: asyncio.Task[None] | None = None

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        return self.hassette.config.logging.app_handler

    def is_released(self) -> bool:
        return self._released_event.is_set()

    async def wait_released(self, *, timeout: float | None = None) -> bool:
        if self._released_event.is_set():
            return True
        if self.shutdown_event.is_set():
            raise asyncio.CancelledError("App bootstrap coordinator is shutting down")

        release_wait = asyncio.create_task(self._released_event.wait(), name="app_bootstrap_coordinator:release_wait")
        shutdown_wait = asyncio.create_task(self.shutdown_event.wait(), name="app_bootstrap_coordinator:shutdown_wait")
        try:
            done, _ = await asyncio.wait(
                {release_wait, shutdown_wait},
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                return False
            if shutdown_wait in done and shutdown_wait.result():
                raise asyncio.CancelledError("App bootstrap coordinator shut down before release")
            return self._released_event.is_set()
        finally:
            for task in (release_wait, shutdown_wait):
                if not task.done():
                    task.cancel()
            await asyncio.gather(release_wait, shutdown_wait, return_exceptions=True)

    async def on_initialize(self) -> None:
        self.logger.debug("Dependencies ready, wiring bootstrap coordinator")
        mark_ready(self, reason="bootstrap coordinator wired")
        self._bootstrap_task = self.task_bucket.spawn(
            self._await_initial_state_capability(),
            name="app_bootstrap_coordinator:await_release",
        )

    async def _await_initial_state_capability(self) -> None:
        try:
            released = await self.hassette.state_proxy.wait_initial_state_capability()
        except asyncio.CancelledError:
            self.logger.debug("Bootstrap coordinator wait cancelled")
            raise

        if released and not self.shutdown_event.is_set() and not self._released_event.is_set():
            self.logger.debug("Initial state capability reached; releasing app bootstrap")
            self._released_event.set()

    async def on_shutdown(self) -> None:
        mark_not_ready(self, reason="shutting-down")
        if self._bootstrap_task is not None:
            self._bootstrap_task.cancel()
            await asyncio.gather(self._bootstrap_task, return_exceptions=True)
            self._bootstrap_task = None
