import asyncio
import logging
import traceback
import typing
from typing import Any, Protocol

from hassette.events import HassetteServiceEvent
from hassette.exceptions import InvalidLifecycleTransitionError
from hassette.types.enums import ResourceStatus
from hassette.types.types import CoroLikeT

LOGGER = logging.getLogger(__name__)


# Valid ResourceStatus transitions. This is the authoritative table for the entire framework.
# All code paths that change status must go through the setter (or use _status directly to bypass,
# e.g. _force_terminal).
VALID_TRANSITIONS: dict[ResourceStatus, frozenset[ResourceStatus]] = {
    ResourceStatus.NOT_STARTED: frozenset(
        {
            ResourceStatus.STARTING,
            ResourceStatus.STOPPING,
            ResourceStatus.EXHAUSTED_COOLING,  # budget exhausted before first start (timing edge)
            ResourceStatus.EXHAUSTED_DEAD,  # budget exhausted before first start (timing edge)
        }
    ),
    ResourceStatus.STARTING: frozenset(
        {
            ResourceStatus.RUNNING,
            ResourceStatus.FAILED,
            ResourceStatus.STOPPED,
            ResourceStatus.STOPPING,
            ResourceStatus.EXHAUSTED_COOLING,  # budget exhausted while restarting (timing edge)
            ResourceStatus.EXHAUSTED_DEAD,  # budget exhausted while restarting (timing edge)
        }
    ),
    ResourceStatus.RUNNING: frozenset(
        {
            ResourceStatus.STOPPING,
            ResourceStatus.STOPPED,  # natural service completion (_serve_wrapper normal return)
            ResourceStatus.FAILED,
            ResourceStatus.CRASHED,
            ResourceStatus.EXHAUSTED_COOLING,  # budget exhausted while running (timing edge)
            ResourceStatus.EXHAUSTED_DEAD,  # budget exhausted while running (timing edge)
        }
    ),
    ResourceStatus.STOPPING: frozenset({ResourceStatus.STOPPED, ResourceStatus.FAILED}),
    ResourceStatus.STOPPED: frozenset({ResourceStatus.STARTING}),  # restart
    ResourceStatus.FAILED: frozenset(
        {
            ResourceStatus.STARTING,  # restart
            ResourceStatus.STOPPING,  # shutdown after failure
            ResourceStatus.STOPPED,  # handle_stop after failure
            ResourceStatus.EXHAUSTED_COOLING,  # budget exhausted, transient
            ResourceStatus.EXHAUSTED_DEAD,  # budget exhausted, temporary
        }
    ),
    ResourceStatus.CRASHED: frozenset(
        {
            ResourceStatus.STARTING,  # restart
            ResourceStatus.STOPPING,  # shutdown after crash
            ResourceStatus.STOPPED,  # handle_stop after crash
            ResourceStatus.EXHAUSTED_DEAD,  # fatal, permanent
        }
    ),
    ResourceStatus.EXHAUSTED_COOLING: frozenset(
        {
            ResourceStatus.STARTING,  # restart after cooldown
            ResourceStatus.STOPPING,  # shutdown while cooling
            ResourceStatus.EXHAUSTED_DEAD,  # cooldown cycles exceeded
        }
    ),
    ResourceStatus.EXHAUSTED_DEAD: frozenset({ResourceStatus.STOPPING}),  # shutdown while dead
}


class _TaskBucketP(Protocol):
    def spawn(self, coro: CoroLikeT, *, name: str | None = None) -> asyncio.Task: ...
    def cancel_all_sync(self) -> None: ...
    async def cancel_all(self) -> None: ...


class _HassetteConfigP(Protocol):
    strict_lifecycle: bool


class _HassetteP(Protocol):
    config: _HassetteConfigP

    async def send_event(self, event: Any) -> None: ...


# shim for typing only - LifecycleMixin needs these attributes to be present
# but we don't want to enforce inheritance from Resource or HassetteBase at runtime
if typing.TYPE_CHECKING:

    class _LifecycleHostP(Protocol):
        logger: logging.Logger
        hassette: _HassetteP
        role: Any
        class_name: str
        unique_name: str
        task_bucket: _TaskBucketP

        def _create_service_status_event(
            self,
            status: ResourceStatus,
            exception: Exception | None = None,
            ready: bool = False,
            ready_phase: str | None = None,
        ) -> "HassetteServiceEvent": ...

        async def initialize(self, *args, **kwargs) -> None: ...
else:

    class _LifecycleHostP:  # runtime stub (empty)
        pass


class LifecycleMixin(_LifecycleHostP):
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

    shutdown_completed: bool = False
    """Flag indicating that shutdown has fully completed (set in _finalize_shutdown)."""

    def __init__(self) -> None:
        self.ready_event = asyncio.Event()
        self.shutdown_event = asyncio.Event()
        self._ready_reason = None
        self._previous_status = ResourceStatus.NOT_STARTED
        self._status = ResourceStatus.NOT_STARTED
        self._init_task: asyncio.Task | None = None
        self.shutdown_completed = False

    @property
    def status(self) -> ResourceStatus:
        return self._status

    @status.setter
    def status(self, value: ResourceStatus) -> None:
        old = self._status
        if old == value:
            return

        # Guard: skip validation when the object is not fully constructed (hassette not yet set).
        if hasattr(self, "hassette"):
            allowed = VALID_TRANSITIONS.get(old, frozenset())
            if value not in allowed:
                if getattr(self.hassette.config, "strict_lifecycle", False) is True:
                    raise InvalidLifecycleTransitionError(
                        from_status=old,
                        to_status=value,
                        resource_name=getattr(self, "unique_name", repr(self)),
                    )
                frame_summary = "".join(traceback.format_stack(limit=3)[:-1]).strip()
                LOGGER.warning(
                    "Invalid lifecycle transition for '%s': %r → %r\n%s",
                    getattr(self, "unique_name", repr(self)),
                    old,
                    value,
                    frame_summary,
                )

        LOGGER.debug("%s: %s → %s", getattr(self, "unique_name", repr(self)), old, value)

        self._previous_status = old
        self._status = value

    @property
    def task(self) -> asyncio.Task | None:
        return self._init_task

    def start(self) -> None:
        """Start the instance by spawning its initialize method in a task."""
        self.shutdown_completed = False

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
            return

        self._ready_reason = reason
        self.ready_event.clear()

    def request_shutdown(self, reason: str | None = None) -> None:
        """Set the sticky shutdown flag. Idempotent."""
        if not self.shutdown_event.is_set():
            self.logger.info("%s shutdown requested: %s", self.unique_name, reason or "no reason", stacklevel=2)
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

    async def handle_stop(self) -> None:
        if self.status == ResourceStatus.STOPPED:
            self.logger.debug("%s already stopped", self.unique_name, stacklevel=2)
            return

        self.logger.debug("%s stopping", self.unique_name, stacklevel=2)
        self.status = ResourceStatus.STOPPED
        self.mark_not_ready("Stopped")
        event = self._create_service_status_event(
            ResourceStatus.STOPPED, ready=self.is_ready(), ready_phase=self._ready_reason
        )
        await self.hassette.send_event(event)

    async def handle_failed(self, exception: Exception | BaseException) -> None:
        if self.status == ResourceStatus.FAILED:
            self.logger.debug("%s already in failed state", self.unique_name, stacklevel=2)
            return

        self.logger.exception("%s failed: %s - %s", self.unique_name, type(exception).__name__, str(exception))
        self.status = ResourceStatus.FAILED
        self.mark_not_ready("Failed")
        event = self._create_service_status_event(
            ResourceStatus.FAILED, exception, ready=self.is_ready(), ready_phase=self._ready_reason
        )
        await self.hassette.send_event(event)

    async def handle_running(self) -> None:
        if self.status == ResourceStatus.RUNNING:
            self.logger.debug("%s already running", self.unique_name, stacklevel=2)
            return

        self.logger.debug("%s running", self.unique_name, stacklevel=2)
        self.status = ResourceStatus.RUNNING
        event = self._create_service_status_event(
            ResourceStatus.RUNNING, ready=self.is_ready(), ready_phase=self._ready_reason
        )
        await self.hassette.send_event(event)

    async def handle_starting(self) -> None:
        if self.status == ResourceStatus.STARTING:
            self.logger.debug("%s already starting", self.unique_name, stacklevel=2)
            return
        self.logger.debug("%s starting", self.unique_name, stacklevel=2)
        self.status = ResourceStatus.STARTING
        event = self._create_service_status_event(
            ResourceStatus.STARTING, ready=self.is_ready(), ready_phase=self._ready_reason
        )
        await self.hassette.send_event(event)

    async def handle_crash(self, exception: Exception) -> None:
        if self.status == ResourceStatus.CRASHED:
            self.logger.debug("%s already in crashed state", self.unique_name, stacklevel=2)
            return

        self.logger.error("%s crashed: %s - %s", self.unique_name, type(exception).__name__, str(exception))
        self.status = ResourceStatus.CRASHED
        self.mark_not_ready("Crashed")
        event = self._create_service_status_event(
            ResourceStatus.CRASHED, exception, ready=self.is_ready(), ready_phase=self._ready_reason
        )
        await self.hassette.send_event(event)

    def _create_service_status_event(
        self,
        status: ResourceStatus,
        exception: Exception | BaseException | None = None,
        ready: bool = False,
        ready_phase: str | None = None,
    ) -> HassetteServiceEvent:
        return HassetteServiceEvent.from_data(
            resource_name=self.class_name,
            role=self.role,
            status=status,
            previous_status=self._previous_status,
            exception=exception,
            ready=ready,
            ready_phase=ready_phase,
        )
