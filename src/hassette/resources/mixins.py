import asyncio
import typing
from logging import Logger, getLogger
from typing import Any, Protocol

from hassette_wire import ResourceStatus

from hassette.resources.teardown import TeardownReport
from hassette.types.types import CoroLikeT

if typing.TYPE_CHECKING:
    from hassette.types.enums import ResourceRole

LOGGER = getLogger(__name__)


class _TaskBucketP(Protocol):
    def spawn(self, coro: CoroLikeT, *, name: str | None = None) -> asyncio.Task: ...
    def cancel_all_sync(self) -> None: ...
    async def cancel_all(self, *, timeout: float | None = None) -> "tuple[str, ...]": ...
    def reopen(self) -> None: ...


class _LifecycleConfigP(Protocol):
    shutdown_timeout_seconds: float
    task_cancellation_timeout_seconds: float


class _HassetteConfigP(Protocol):
    lifecycle: _LifecycleConfigP


class _HassetteP(Protocol):
    config: _HassetteConfigP
    shutdown_event: asyncio.Event
    loop: asyncio.AbstractEventLoop
    loop_thread_id: int | None

    async def send_event(self, event: Any) -> None: ...


# shim for typing only - LifecycleMixin needs these attributes to be present
# but we don't want to enforce inheritance from Resource or HassetteBase at runtime
if typing.TYPE_CHECKING:

    class _LifecycleHostP(Protocol):
        lifecycle_logger: Logger
        hassette: _HassetteP
        role: ResourceRole
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

    _pending_start_task: asyncio.Task | None = None
    """``start()``'s own joiner task. Stays set for the entire duration of the joiner's
    ``initialize()`` call -- including the full run of ``_init_task`` once ``coordinate_initialize()``
    creates it -- and is cleared only when the joiner itself finishes (via its own done-callback)
    or when ``_observe_active_initializer()`` cancels it explicitly. The two fields are therefore
    both non-``None`` for most of a normal initialization, not just briefly at the start.

    ``start()`` does not assign ``_init_task`` synchronously -- that only happens once the
    joiner actually runs ``coordinate_initialize()``, which can be several event-loop turns
    later. Without this field, a ``shutdown()`` called immediately after ``start()`` (before the
    joiner gets a turn) would see no active initializer and complete cleanly, only for the
    still-pending joiner to resume afterward and initialize the resource anyway -- leaving it
    running after an explicit shutdown. ``_observe_active_initializer()`` cancels this task
    (in addition to ``_init_task``) before a shutdown attempt proceeds.
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
    consumes a report with ``is_restart_safe`` ``True``; a report with ``is_restart_safe``
    ``False`` has no in-process reset path.
    """

    _shutdown_deadline: float | None = None
    """Absolute loop time by which the current shutdown attempt's operation must finish.

    Set by the operation's owner before it calls ``shutdown()`` (the root for each exit stage,
    ``AppLifecycleService`` for a runtime instance operation) and passed down to children; a caller
    joining an attempt in flight can only tighten it (``shutdown_deadline.tighten_shutdown_deadline()``).
    Leaves clamp their own bounds to it. ``None`` means no owner set one: leaves keep their own caps
    and interior nodes wait without a bound. Reset when an accepted initialization consumes the
    previous attempt.
    """

    shutdown_hook_timeout_applies: typing.ClassVar[bool] = True
    """Whether ``shutdown_timeout_seconds`` bounds this resource's shutdown hooks.

    ``False`` only for the foundation services the root stops in its foundation stage, whose
    framework steps carry fixed caps of their own; their hooks are bounded by the stage's deadline
    alone.
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
        self._pending_start_task = None
        self._shutdown_task = None
        self._shutdown_body_task = None
        self._teardown_report = None
        self._shutdown_deadline = None

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
        shutdown attempt has stored its final report (regardless of ``is_restart_safe``), and is
        cleared only when the first accepted new initialization consumes a restart-safe report.
        """
        return self._teardown_report is not None

    @property
    def teardown_report(self) -> TeardownReport | None:
        """Read-only: the current unconsumed teardown report, or ``None``.

        ``None`` means no completed teardown attempt exists yet, or a prior restart-safe report
        has already been consumed by a new initialization attempt. A caller that needs the exact
        report from a specific shutdown call should use the value ``await resource.shutdown()``
        returns instead — this property only reflects the current, possibly-since-superseded
        state.
        """
        return self._teardown_report

    @property
    def is_restart_safe(self) -> bool | None:
        """Read-only: ``teardown_report.is_restart_safe``, or ``None`` if no report exists yet."""
        report = self._teardown_report
        return report.is_restart_safe if report is not None else None

    @property
    def status(self) -> ResourceStatus:
        """Current lifecycle status.

        Assigning a new value always applies it and logs the transition at DEBUG; assigning the
        current value is a no-op.
        """
        return self._status

    @status.setter
    def status(self, value: ResourceStatus) -> None:
        old = self._status
        if old == value:
            return

        LOGGER.debug("%s: %s → %s", self.unique_name, old, value)

        self._previous_status = old
        self._status = value

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
