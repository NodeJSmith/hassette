import asyncio
import traceback
import typing
from logging import Logger, getLogger
from typing import Any, Protocol

from hassette.exceptions import InvalidLifecycleTransitionError
from hassette.types.enums import ResourceStatus
from hassette.types.types import CoroLikeT

LOGGER = getLogger(__name__)


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
        logger: Logger
        hassette: _HassetteP
        role: Any
        class_name: str
        unique_name: str
        task_bucket: _TaskBucketP

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
