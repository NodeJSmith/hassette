import asyncio
import logging
import typing
import uuid
from abc import abstractmethod
from collections.abc import Coroutine
from contextlib import asynccontextmanager, suppress
from logging import Logger, getLogger
from typing import Any, ClassVar, Protocol, TypeVar, final

from typing_extensions import deprecated

from hassette.const.misc import LOG_LEVELS
from hassette.enums import ResourceRole, ResourceStatus
from hassette.events import HassetteServiceEvent, ServiceStatusPayload

if typing.TYPE_CHECKING:
    from hassette import Hassette, TaskBucket

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
        ) -> HassetteServiceEvent: ...

        async def initialize(self, *args, **kwargs) -> None: ...
else:

    class _LifecycleHostStubs:  # runtime stub (empty)
        pass


class FinalMeta(type):
    def __new__(mcls, name, bases, ns):
        # Collect names of all @final methods on base classes
        finals = {attr for base in bases for attr, val in base.__dict__.items() if getattr(val, "__final__", False)}
        # Check for overrides
        for attr in finals:
            if attr in ns:
                raise TypeError(f"Cannot override final method '{attr}' in class '{name}'")
        return super().__new__(mcls, name, bases, ns)


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
            self.logger.warning("%s '%s' is already started or running", self.role, self.class_name, stacklevel=2)
            return

        self.logger.debug("Starting '%s' %s", self.class_name, self.role)
        self._init_task = self.task_bucket.spawn(self.initialize(), name="resource:resource_initialize")

    def cancel(self) -> None:
        """Cancel the main task of the instance, if it is running."""
        if self._init_task and not self._init_task.done():
            self._init_task.cancel()
            self.logger.debug("Cancelled '%s' %s task", self.class_name, self.role)
            return

        self.logger.debug("%s '%s' has no running task to cancel", self.role, self.class_name)

    # --------- readiness
    def mark_ready(self, reason: str | None = None) -> None:
        """Mark the instance as ready.

        Args:
            reason (str | None): Optional reason for readiness.

        """
        self._ready_reason = reason
        self.ready_event.set()

    def mark_not_ready(self, reason: str | None = None) -> None:
        """Mark the instance as not ready.

        Args:
            reason (str | None): Optional reason for lack of readiness.
        """
        if not self.ready_event.is_set():
            self.logger.debug("%s is already not ready, skipping reason %s", self.unique_name, reason)

        self._ready_reason = reason
        self.ready_event.clear()

    def request_shutdown(self, reason: str | None = None) -> None:
        """Set the sticky shutdown flag. Idempotent."""
        if not self.shutdown_event.is_set():
            self.logger.debug("Shutdown requested for %s (%s)", self.unique_name, reason or "")
            self.shutdown_event.set()
        # clear readiness early so callers back off
        self.mark_not_ready(reason or "shutdown requested")

    def is_ready(self) -> bool:
        """Check if the instance is ready.

        Returns:
            bool: True if the instance is ready, False otherwise.
        """
        return self.ready_event.is_set()

    async def wait_ready(self, timeout: float | None = None) -> None:
        """Wait until the instance is marked as ready.

        Args:
            timeout (float | None): Optional timeout in seconds to wait for readiness.
                                   If None, wait indefinitely.

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
            self.logger.warning("%s '%s' is already stopped", self.role, self.class_name, stacklevel=2)
            return

        self.logger.info("Stopping %s '%s'", self.role, self.class_name)
        self.status = ResourceStatus.STOPPED
        event = self._create_service_status_event(ResourceStatus.STOPPED)
        await self.hassette.send_event(event.topic, event)
        self.mark_not_ready("Stopped")

    async def handle_failed(self, exception: Exception | BaseException) -> None:
        if self.status == ResourceStatus.FAILED:
            self.logger.warning("%s '%s' is already in failed state", self.role, self.class_name, stacklevel=2)
            return

        self.logger.error("%s '%s' failed: %s - %s", self.role, self.class_name, type(exception), str(exception))
        self.status = ResourceStatus.FAILED
        event = self._create_service_status_event(ResourceStatus.FAILED, exception)
        await self.hassette.send_event(event.topic, event)
        self.mark_not_ready("Failed")

    @asynccontextmanager
    async def starting(self):
        try:
            await self.handle_starting()
            yield
            await self.handle_running()
        except Exception as e:
            await self.handle_crash(e)
            raise

    async def handle_running(self) -> None:
        if self.status == ResourceStatus.RUNNING:
            self.logger.warning("%s '%s' is already running", self.role, self.class_name, stacklevel=2)
            return

        self.logger.info("Running %s '%s'", self.role, self.class_name)
        self.status = ResourceStatus.RUNNING
        event = self._create_service_status_event(ResourceStatus.RUNNING)
        await self.hassette.send_event(event.topic, event)

    async def handle_starting(self) -> None:
        if self.status == ResourceStatus.STARTING:
            self.logger.warning("%s '%s' is already starting", self.role, self.class_name, stacklevel=2)
            return
        self.logger.info("Starting %s '%s'", self.role, self.class_name)
        self.status = ResourceStatus.STARTING
        event = self._create_service_status_event(ResourceStatus.STARTING)
        await self.hassette.send_event(event.topic, event)

    async def handle_crash(self, exception: Exception) -> None:
        if self.status == ResourceStatus.CRASHED:
            self.logger.warning("%s '%s' is already in crashed state", self.role, self.class_name, stacklevel=2)
            return

        self.logger.exception("%s '%s' crashed", self.role, self.class_name)
        self.status = ResourceStatus.CRASHED
        event = self._create_service_status_event(ResourceStatus.CRASHED, exception)
        await self.hassette.send_event(event.topic, event)
        self.mark_not_ready("Crashed")

    def _create_service_status_event(self, status: ResourceStatus, exception: Exception | BaseException | None = None):
        return ServiceStatusPayload.create_event(
            resource_name=self.class_name,
            role=self.role,
            status=status,
            previous_status=self._previous_status,
            exc=exception,
        )


class _HassetteBase:
    unique_id: str
    """Unique identifier for the instance."""

    logger: Logger
    """Logger for the instance."""

    unique_name: str
    """Unique name for the instance."""

    class_name: typing.ClassVar[str]
    """Name of the class, set on subclassing."""

    role: typing.ClassVar[ResourceRole] = ResourceRole.BASE
    """Role of the resource, e.g. 'App', 'Service', etc."""

    hassette: "Hassette"
    """Reference to the Hassette instance."""

    def __init_subclass__(cls) -> None:
        cls.class_name = cls.__name__

    def __init__(self, hassette: "Hassette", unique_name_prefix: str | None = None) -> None:
        """
        Initialize the class with a reference to the Hassette instance.

        Args:
            hassette (Hassette): The Hassette instance this resource belongs to.
            unique_name_prefix (str | None): Optional prefix for the unique name. If None, the class name is used.
        """
        self.unique_id = uuid.uuid4().hex
        self.unique_name = f"{unique_name_prefix or type(self).__name__}.{self.unique_id[:8]}"
        if unique_name_prefix == "hassette":
            self.logger = getLogger("hassette")
        else:
            self.logger = getLogger("hassette").getChild(self.unique_name)

        self.hassette = hassette
        self.logger.debug("Creating instance of '%s'", self.class_name)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} unique_name={self.unique_name}>"

    @deprecated("Use self.logger.setLevel(...) instead")
    def set_logger_to_level(self, level: LOG_LEVELS) -> None:
        """Configure a logger to log at the specified level independently of its parent."""
        self.logger.setLevel(level)

    @deprecated("Use set_logger_to_level('DEBUG') instead")
    def set_logger_to_debug(self) -> None:
        """Configure a logger to log at DEBUG level independently of its parent."""
        self.logger.setLevel("DEBUG")


class Resource(_HassetteBase, LifecycleMixin, metaclass=FinalMeta):
    """Base class for resources in the Hassette framework."""

    role: ClassVar[ResourceRole] = ResourceRole.RESOURCE
    """Role of the resource, e.g. 'App', 'Service', etc."""

    task_bucket: "TaskBucket"
    """Task bucket for managing tasks owned by this instance."""

    _shutting_down: bool = False
    """Flag indicating whether the instance is in the process of shutting down."""

    _initializing: bool = False
    """Flag indicating whether the instance is in the process of starting up."""

    def __init__(
        self, hassette: "Hassette", unique_name_prefix: str | None = None, task_bucket: "TaskBucket | None" = None
    ) -> None:
        """
        Initialize the resource.

        Args:
            hassette (Hassette): The Hassette instance this resource belongs to.
            unique_name_prefix (str | None): Optional prefix for the unique name. If None, the class name is used.
            task_bucket (TaskBucket | None): Optional TaskBucket for managing tasks. If None, a new one is created.

        """
        from hassette.core.resources.tasks import TaskBucket

        _HassetteBase.__init__(self, hassette, unique_name_prefix=unique_name_prefix)
        LifecycleMixin.__init__(self)

        self.task_bucket = task_bucket or TaskBucket(
            self.hassette, name=self.unique_name, unique_name_prefix=self.class_name
        )

    # --- developer-facing hooks (override as needed) -------------------
    async def before_initialize(self) -> None:
        """Optional: prepare to accept new work, allocate sockets, queues, temp files, etc."""
        # Default: nothing. Subclasses override when they own resources.

    async def on_initialize(self) -> None:
        """Primary hook: perform your own initialization (sockets, queues, temp files…)."""
        # Default: nothing. Subclasses override when they own resources.

    async def after_initialize(self) -> None:
        """Optional: finalize initialization, signal readiness, etc."""
        # Default: nothing. Subclasses override when they own resources.

    @final
    async def initialize(self) -> None:
        """Initialize the instance by calling the lifecycle hooks in order."""
        if self._initializing:
            return
        self._initializing = True

        self.logger.debug("Initializing '%s' %s", self.class_name, self.role)
        await self.handle_starting()

        try:
            for method in [self.before_initialize, self.on_initialize, self.after_initialize]:
                try:
                    await method()

                except asyncio.CancelledError:
                    # Cooperative cancellation of hooks; still ensure cleanup + STOPPED
                    with suppress(Exception):
                        await self.handle_failed(asyncio.CancelledError())
                    raise

                except Exception as e:
                    # Hooks blew up: record failure, but continue to clean up
                    with suppress(Exception):
                        await self.handle_failed(e)
                    raise

        finally:
            self._initializing = False
            await self.handle_running()

    # --- developer-facing hooks (override as needed) -------------------
    async def before_shutdown(self) -> None:
        """Optional: stop accepting new work, signal loops to wind down, etc."""
        # Default: cancel an in-flight initialize() task if you used Resource.start()
        self.cancel()

    async def on_shutdown(self) -> None:
        """Primary hook: release your own stuff (sockets, queues, temp files…)."""
        # Default: nothing. Subclasses override when they own resources.

    async def after_shutdown(self) -> None:
        """Optional: last-chance actions after on_shutdown, before cleanup/STOPPED."""
        # Default: nothing.

    @final
    async def shutdown(self) -> None:
        """Shutdown the instance by calling the lifecycle hooks in order."""
        if self._shutting_down:
            return
        self._shutting_down = True
        self.request_shutdown("shutdown")

        try:
            for method in [self.before_shutdown, self.on_shutdown, self.after_shutdown]:
                try:
                    await method()

                except asyncio.CancelledError:
                    self.logger.warning(
                        "%s '%s' shutdown hook was cancelled, forcing cleanup", self.role, self.class_name
                    )
                    # Cooperative cancellation of hooks; still ensure cleanup + STOPPED
                    with suppress(Exception):
                        await self.handle_failed(asyncio.CancelledError())
                    raise

                except Exception as e:
                    self.logger.exception("Error during shutdown of %s '%s': %s", self.role, self.class_name, e)
                    # Hooks blew up: record failure, but continue to clean up
                    with suppress(Exception):
                        await self.handle_failed(e)

        finally:
            # Always free tasks; then mark STOPPED and emit event
            try:
                await self.cleanup()
            except Exception:
                self.logger.exception("Error during cleanup of %s '%s'", self.role, self.class_name)

            if not self.hassette.event_streams_closed:
                try:
                    await self.handle_stop()
                except Exception:
                    self.logger.exception("Error during stopping of %s '%s'", self.role, self.class_name)
            else:
                self.logger.info(
                    "Skipping STOPPED event for %s '%s' as event streams are closed", self.role, self.class_name
                )

            self._shutting_down = False

    async def restart(self) -> None:
        """Restart the instance by shutting it down and re-initializing it."""
        self.logger.debug("Restarting '%s' %s", self.class_name, self.role)
        await self.shutdown()
        await self.initialize()

    async def cleanup(self) -> None:
        """Cleanup resources owned by the instance.

        This method is called during shutdown to ensure that all resources are properly released.
        """
        self.cancel()
        await self.task_bucket.cancel_all()
        self.logger.debug("Cleaned up resources for %s '%s'", self.role, self.class_name)


class Service(Resource):
    """Base class for services in the Hassette framework."""

    role: ClassVar[ResourceRole] = ResourceRole.SERVICE
    """Role of the service, e.g. 'App', 'Service', etc."""

    _serve_task: asyncio.Task | None = None

    @abstractmethod
    async def serve(self) -> None:
        """Subclasses MUST override: run until cancelled or finished."""
        raise NotImplementedError

    # Start: spin up the supervised serve() task
    async def on_initialize(self) -> None:
        # Do any service-specific setup, then launch serve()
        self._serve_task = self.task_bucket.spawn(self._serve_wrapper(), name=f"service:serve:{self.class_name}")

    async def _serve_wrapper(self) -> None:
        try:
            # We're “RUNNING” as soon as on_initialize returns; readiness is up to the service
            await self.serve()
            # Normal return → graceful stop path
            await self.handle_stop()
        except asyncio.CancelledError:
            # Cooperative shutdown
            with suppress(Exception):
                await self.handle_stop()
            raise
        except Exception as e:
            self.logger.exception("%s '%s' serve() task failed", self.role, self.class_name)
            # Crash/failure path
            await self.handle_failed(e)

    # Shutdown: cancel the serve() task and wait for it
    async def on_shutdown(self) -> None:
        # Flip any internal flags if you have them; then cancel the loop
        if self.is_running() and self._serve_task:
            self._serve_task.cancel()
            self.logger.info("Cancelled serve() task for %s '%s'", self.role, self.class_name)
            with suppress(asyncio.CancelledError):
                await self._serve_task

    def is_running(self) -> bool:
        return self._serve_task is not None and not self._serve_task.done()
