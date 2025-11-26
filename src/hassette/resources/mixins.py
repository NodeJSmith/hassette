import asyncio
import typing
from collections.abc import Coroutine
from typing import Any, Protocol, TypeVar

from hassette.types.enums import ResourceStatus

if typing.TYPE_CHECKING:
    import logging

    from hassette.events import HassetteServiceEvent

T = TypeVar("T")
CoroLikeT = Coroutine[Any, Any, T]


class _TaskBucketP(Protocol):
    def spawn(self, coro: CoroLikeT, *, name: str | None = None) -> asyncio.Task: ...
    async def cancel_all(self) -> None: ...


class _HassetteP(Protocol):
    async def send_event(self, topic: str, payload: Any) -> None: ...


# shim for typing only - LifecycleMixin needs these attributes to be present
# but we don't want to enforce inheritance from Resource or HassetteBase at runtime
if typing.TYPE_CHECKING:

    class _LifecycleHostStubs(Protocol):
        logger: logging.Logger
        hassette: _HassetteP
        role: Any
        class_name: str
        unique_name: str
        task_bucket: _TaskBucketP

        def _create_service_status_event(
            self, status: ResourceStatus, exception: Exception | None = None
        ) -> "HassetteServiceEvent": ...

        async def initialize(self, *args, **kwargs) -> None: ...
else:

    class _LifecycleHostStubs:  # runtime stub (empty)
        pass


class LifecycleMixin(_LifecycleHostStubs):
    ready_event: asyncio.Event
    """Event to signal readiness of the instance."""

    shutdown_event: asyncio.Event
    """Event to signal shutdown of the instance."""

    _ready_reason: str | None
    """Optional reason for readiness or lack thereof."""

    _init_task: asyncio.Task | None = None
    """Initialization task for the instance."""

    _previous_status: ResourceStatus = ResourceStatus.NOT_STARTED
    """Previous status of the instance."""

    _status: ResourceStatus = ResourceStatus.NOT_STARTED
    """Current status of the instance."""

    def __init__(self) -> None:
        self.ready_event = asyncio.Event()
        self.shutdown_event = asyncio.Event()
        self._ready_reason = None
        self._previous_status = ResourceStatus.NOT_STARTED
        self._status = ResourceStatus.NOT_STARTED
        self._init_task: asyncio.Task | None = None

    # --------- props
    @property
    def status(self) -> ResourceStatus:
        return self._status

    @status.setter
    def status(self, value: ResourceStatus) -> None:
        self._previous_status = self._status
        self._status = value

    @property
    def task(self) -> asyncio.Task | None:
        return self._init_task

    # --------- lifecycle ops
    def start(self) -> None:
        """Start the instance by spawning its initialize method in a task."""
        # create a new event each time we start
        self.shutdown_event = asyncio.Event()

        if self._init_task and not self._init_task.done():
            self.logger.debug("%s already started or running", self.unique_name, stacklevel=2)
            return

        self.logger.debug("%s starting", self.unique_name)
        self._init_task = self.task_bucket.spawn(self.initialize(), name="resource:resource_initialize")

    def cancel(self) -> None:
        """Cancel the main task of the instance, if it is running."""
        if self._init_task and not self._init_task.done():
            self._init_task.cancel()
            self.logger.debug("%s cancelled task", self.unique_name)
            return

        self.logger.debug("%s no running task to cancel", self.unique_name)

    # --------- readiness
    def mark_ready(self, reason: str | None = None) -> None:
        """Mark the instance as ready.

        Args:
            reason: Optional reason for readiness.
        """
        if self.ready_event.is_set():
            self.logger.debug("%s already ready, skipping reason %s", self.unique_name, reason)
            return
        self.logger.debug("ready: %s", reason or "no reason provided")
        self._ready_reason = reason
        self.ready_event.set()

    def mark_not_ready(self, reason: str | None = None) -> None:
        """Mark the instance as not ready.

        Args:
            reason: Optional reason for lack of readiness.
        """
        if not self.ready_event.is_set():
            self.logger.debug("%s already not ready, skipping reason %s", self.unique_name, reason)

        self._ready_reason = reason
        self.ready_event.clear()

    def request_shutdown(self, reason: str | None = None) -> None:
        """Set the sticky shutdown flag. Idempotent."""
        if not self.shutdown_event.is_set():
            self.logger.debug("%s shutdown requested: %s", self.unique_name, reason or "")
            self.shutdown_event.set()
        # clear readiness early so callers back off
        self.mark_not_ready(reason or "shutdown requested")

    def is_ready(self) -> bool:
        """Check if the instance is ready.

        Returns:
            True if the instance is ready, False otherwise.
        """
        return self.ready_event.is_set()

    async def wait_ready(self, timeout: float | None = None) -> None:
        """Wait until the instance is marked as ready.

        Args:
            timeout: Optional timeout in seconds to wait for readiness. If None, wait indefinitely.

        Raises:
            TimeoutError: If the timeout is reached before the instance is ready.
        """
        if timeout is None:
            await self.ready_event.wait()
        else:
            await asyncio.wait_for(self.ready_event.wait(), timeout)

    # --------- transitions
    async def handle_stop(self) -> None:
        if self.status == ResourceStatus.STOPPED:
            self.logger.debug("%s already stopped", self.unique_name, stacklevel=2)
            return

        self.logger.debug("%s stopping", self.unique_name, stacklevel=2)
        self.status = ResourceStatus.STOPPED
        event = self._create_service_status_event(ResourceStatus.STOPPED)
        await self.hassette.send_event(event.topic, event)
        self.mark_not_ready("Stopped")

    async def handle_failed(self, exception: Exception | BaseException) -> None:
        if self.status == ResourceStatus.FAILED:
            self.logger.debug("%s already in failed state", self.unique_name, stacklevel=2)
            return

        self.logger.error("%s failed: %s - %s", self.unique_name, type(exception).__name__, str(exception))
        self.status = ResourceStatus.FAILED
        event = self._create_service_status_event(ResourceStatus.FAILED, exception)
        await self.hassette.send_event(event.topic, event)
        self.mark_not_ready("Failed")

    async def handle_running(self) -> None:
        if self.status == ResourceStatus.RUNNING:
            self.logger.debug("%s already running", self.unique_name, stacklevel=2)
            return

        self.logger.debug("%s running", self.unique_name, stacklevel=2)
        self.status = ResourceStatus.RUNNING
        event = self._create_service_status_event(ResourceStatus.RUNNING)
        await self.hassette.send_event(event.topic, event)

    async def handle_starting(self) -> None:
        if self.status == ResourceStatus.STARTING:
            self.logger.debug("%s already starting", self.unique_name, stacklevel=2)
            return
        self.logger.debug("%s starting", self.unique_name, stacklevel=2)
        self.status = ResourceStatus.STARTING
        event = self._create_service_status_event(ResourceStatus.STARTING)
        await self.hassette.send_event(event.topic, event)

    async def handle_crash(self, exception: Exception) -> None:
        if self.status == ResourceStatus.CRASHED:
            self.logger.debug("%s already in crashed state", self.unique_name, stacklevel=2)
            return

        self.logger.error("%s crashed: %s - %s", self.unique_name, type(exception).__name__, str(exception))
        self.status = ResourceStatus.CRASHED
        event = self._create_service_status_event(ResourceStatus.CRASHED, exception)
        await self.hassette.send_event(event.topic, event)
        self.mark_not_ready("Crashed")

    def _create_service_status_event(self, status: ResourceStatus, exception: Exception | BaseException | None = None):
        from hassette.events import HassetteServiceEvent

        return HassetteServiceEvent.from_data(
            resource_name=self.class_name,
            role=self.role,
            status=status,
            previous_status=self._previous_status,
            exception=exception,
        )
