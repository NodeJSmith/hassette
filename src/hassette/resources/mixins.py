import asyncio
import traceback
import typing
from logging import Logger, getLogger
from typing import Any, Protocol

from hassette.exceptions import InvalidLifecycleTransitionError
from hassette.resources.teardown import RestartSafety, TeardownReport
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
    async def cancel_all(self) -> "tuple[str, ...]": ...
    def reopen(self) -> None: ...


class _LifecycleConfigP(Protocol):
    resource_shutdown_timeout_seconds: float
    total_shutdown_timeout_seconds: float


class _HassetteConfigP(Protocol):
    strict_lifecycle: bool
    lifecycle: _LifecycleConfigP


class _HassetteP(Protocol):
    config: _HassetteConfigP
    shutdown_event: asyncio.Event

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
        children: "list[Any]"

        async def initialize(self, *args, **kwargs) -> None: ...
        async def _initialize_body(self) -> None: ...
        async def _shutdown_body(self) -> TeardownReport: ...
        def _force_terminal(self) -> None: ...
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
    """The one resource-owned initialization attempt, including direct ``initialize()`` calls.

    Authoritative: every initialization path (``start()``, direct ``initialize()``, ``restart()``)
    is tracked by this single task. Concurrent initialization callers join this task rather than
    each starting their own attempt.
    """

    _shutdown_task: asyncio.Task | None = None
    """The one resource-owned shutdown attempt. Concurrent shutdown callers join this task."""

    _shutdown_body_task: asyncio.Task | None = None
    """Non-admission diagnostic ownership of the class-specific shutdown body.

    Never decides whether a lifecycle operation may start; keeps a cancellation-resistant
    shutdown body reachable and observable until it actually completes, even after the
    shutdown coordinator itself has returned to its callers.
    """

    _teardown_report: TeardownReport | None = None
    """The final report for the current shutdown attempt.

    ``None`` means no completed teardown attempt exists (never shut down, or a shutdown
    attempt is still in progress). Cleared only when the first accepted new initialization
    consumes a ``RestartSafety.SAFE`` report; a ``RestartSafety.UNSAFE`` report has no
    in-process reset path.
    """

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
        self._init_task = None
        self._shutdown_task = None
        self._shutdown_body_task = None
        self._teardown_report = None

    @property
    def initializing(self) -> bool:
        """Read-only diagnostic: whether the resource-owned initialization task is active.

        Derived from ``_init_task`` rather than a mutable flag — this no longer controls
        lifecycle admission (see ``hassette.resources.lifecycle`` coordinator functions).
        """
        return self._init_task is not None and not self._init_task.done()

    @property
    def shutting_down(self) -> bool:
        """Read-only diagnostic: whether the resource-owned shutdown task is active.

        Derived from ``_shutdown_task`` rather than a mutable flag — this no longer controls
        lifecycle admission (see ``hassette.resources.lifecycle`` coordinator functions).
        """
        return self._shutdown_task is not None and not self._shutdown_task.done()

    @property
    def shutdown_completed(self) -> bool:
        """Read-only diagnostic: whether a completed teardown report exists.

        Derived from ``_teardown_report`` rather than a mutable flag. Becomes ``True`` once a
        shutdown attempt has stored its final report (regardless of ``restart_safety``), and is
        cleared only when the first accepted new initialization consumes a ``SAFE`` report.
        """
        return self._teardown_report is not None

    @property
    def teardown_report(self) -> TeardownReport | None:
        """Read-only: the current unconsumed teardown report, or ``None``.

        ``None`` means no completed teardown attempt exists yet, or a prior ``SAFE`` report has
        already been consumed by a new initialization attempt. A caller that needs the exact
        report from a specific shutdown call should use the value ``await resource.shutdown()``
        returns instead — this property only reflects the current, possibly-since-superseded
        state.
        """
        return self._teardown_report

    @property
    def restart_safety(self) -> RestartSafety | None:
        """Read-only: ``teardown_report.restart_safety``, or ``None`` if no report exists yet."""
        report = self._teardown_report
        return report.restart_safety if report is not None else None

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
