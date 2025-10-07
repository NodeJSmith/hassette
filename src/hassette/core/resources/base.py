import asyncio
import copy
import typing
import uuid
from abc import abstractmethod
from contextlib import asynccontextmanager, suppress
from logging import Logger, getLogger
from typing import ClassVar

from typing_extensions import deprecated

from hassette.enums import ResourceRole, ResourceStatus
from hassette.events import ServiceStatusPayload

if typing.TYPE_CHECKING:
    from hassette.core.core import Hassette
    from hassette.core.resources.tasks import TaskBucket


class _LoggerMixin:
    """Mixin to provide logging capabilities to classes."""

    unique_id: str
    """Unique identifier for the instance."""

    logger: Logger
    """Logger for the instance."""

    unique_name: str
    """Unique name for the instance."""

    def __init__(self, unique_name_prefix: str | None = None) -> None:
        self.unique_id = uuid.uuid4().hex
        self.unique_name = f"{unique_name_prefix or type(self).__name__}.{self.unique_id[:8]}"
        self.logger = getLogger(f"hassette.{self.unique_name}")

    def __repr__(self) -> str:
        return f"<{type(self).__name__} unique_name={self.unique_name}>"

    def set_logger_to_level(self, level: typing.Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]) -> None:
        """Configure a logger to log at the specified level independently of its parent."""
        self.logger.setLevel(level)
        self.logger.propagate = False  # avoid parent's filters

        # Only add a handler if it doesn't already have one

        parent_logger = self.logger.parent
        while True:
            if parent_logger and not parent_logger.handlers:
                parent_logger = parent_logger.parent
            else:
                break

        if not self.logger.handlers and parent_logger and parent_logger.handlers:
            for parent_handler in parent_logger.handlers:
                # This assumes handler can be shallow-copied
                handler = copy.copy(parent_handler)
                handler.setLevel(level)
                self.logger.addHandler(handler)

    @deprecated("Use set_logger_to_level('DEBUG') instead")
    def set_logger_to_debug(self) -> None:
        """Configure a logger to log at DEBUG level independently of its parent."""
        self.set_logger_to_level("DEBUG")


class _HassetteBase(_LoggerMixin):  # pyright: ignore[reportUnusedClass]
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
        super().__init__(unique_name_prefix=unique_name_prefix)
        self.hassette = hassette
        self.logger.debug("Creating instance of '%s'", self.class_name)

    def __repr__(self) -> str:
        return f"<{self.class_name} unique_name={self.unique_name}>"


class Resource(_HassetteBase):
    """Base class for resources in the Hassette framework.

    A Resource class or subclass represents a logical entity within the Hassette framework,
    encapsulating its behavior and state. It is defined to offload lifecycle and status management
    from the individual resource implementations.

    A Resource is defined by having startup/shutdown logic, but does not run forever like a Service
    does.
    """

    role: ClassVar[ResourceRole] = ResourceRole.RESOURCE
    """Role of the resource, e.g. 'App', 'Service', etc."""

    _previous_status: ResourceStatus = ResourceStatus.NOT_STARTED
    """Previous status of the resource."""

    _status: ResourceStatus = ResourceStatus.NOT_STARTED
    """Current status of the resource."""

    _task: asyncio.Task | None = None

    @property
    def status(self) -> ResourceStatus:
        """Current status of the resource."""
        return self._status

    @status.setter
    def status(self, value: ResourceStatus) -> None:
        self._previous_status = self._status
        self._status = value

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

        super().__init__(hassette, unique_name_prefix=unique_name_prefix)

        self.task_bucket = task_bucket or TaskBucket(self.hassette, name=self.unique_name, prefix=self.class_name)
        """Task bucket for managing tasks owned by this instance."""

        self.ready: asyncio.Event = asyncio.Event()
        """Event to signal readiness of the instance."""

        self._ready_reason: str | None = None
        """Optional reason for readiness or lack thereof."""

    def start(self) -> None:
        """Start the resource."""
        if self.status != ResourceStatus.NOT_STARTED:
            self.logger.warning("%s '%s' is already started or running", self.role, self.class_name)
            return

        self.logger.debug("Starting '%s' %s", self.class_name, self.role)
        self._task = self.task_bucket.spawn(self.initialize(), name="resource:resource_initialize")

    def cancel(self) -> None:
        """Stop the resource."""
        if self._task and not self._task.done():
            self._task.cancel()
            self.logger.debug("Cancelled '%s' %s task", self.class_name, self.role)

    def get_task(self) -> asyncio.Task | None:
        return self._task

    async def initialize(self, *args, **kwargs) -> None:
        """Initialize the resource.

        This method can be overridden by subclasses to perform
        resource-specific initialization tasks.
        """
        self.logger.debug("Initializing '%s' %s", self.class_name, self.role)
        await self.handle_running()

    async def shutdown(self, *args, **kwargs) -> None:
        """Shutdown the resource.

        This method can be overridden by subclasses to perform resource-specific shutdown tasks.
        """
        if self.status == ResourceStatus.STOPPED:
            self.logger.warning("%s '%s' is already stopped", self.role, self.class_name)
            return

        self.cancel()
        with suppress(asyncio.CancelledError):
            if self._task:
                await self._task

        self.logger.debug("Shutting down '%s' %s", self.class_name, self.role)
        await self.handle_stop()

    async def restart(self) -> None:
        """Restart the resource."""
        self.logger.debug("Restarting '%s' %s", self.class_name, self.role)
        await self.shutdown()
        await self.initialize()

    def _create_service_status_event(self, status: ResourceStatus, exception: Exception | None = None):
        return ServiceStatusPayload.create_event(
            resource_name=self.class_name,
            role=self.role,
            status=status,
            previous_status=self._previous_status,
            exc=exception,
        )

    def mark_ready(self, reason: str | None = None) -> None:
        """Mark the instance as ready.

        Args:
            reason (str | None): Optional reason for readiness.

        """
        self._ready_reason = reason
        self.ready.set()

    def mark_not_ready(self, reason: str | None = None) -> None:
        """Mark the instance as not ready.

        Args:
            reason (str | None): Optional reason for lack of readiness.
        """
        if not self.ready.is_set():
            self.logger.debug("%s is already not ready, skipping reason %s", self.unique_name, reason)

        self._ready_reason = reason
        self.ready.clear()

    def is_ready(self) -> bool:
        """Check if the instance is ready.

        Returns:
            bool: True if the instance is ready, False otherwise.
        """
        return self.ready.is_set()

    async def wait_ready(self, timeout: float | None = None) -> None:
        """Wait until the instance is marked as ready.

        Args:
            timeout (float | None): Optional timeout in seconds to wait for readiness.
                                   If None, wait indefinitely.

        Raises:
            TimeoutError: If the timeout is reached before the instance is ready.
        """
        if timeout is None:
            await self.ready.wait()
        else:
            await asyncio.wait_for(self.ready.wait(), timeout)

    async def handle_stop(self) -> None:
        """Handle a stop event."""

        self.logger.info("Stopping %s '%s'", self.role, self.class_name)
        self.status = ResourceStatus.STOPPED
        event = self._create_service_status_event(ResourceStatus.STOPPED)
        await self.hassette.send_event(event.topic, event)

        self.mark_not_ready("Stopped")

    async def handle_failed(self, exception: Exception) -> None:
        """Handle a failure event."""

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
        """Handle a running event for the service."""

        # note: we specifically do NOT mark ready here, as the service
        # should make this decision itself when it is actually ready

        if self._previous_status == ResourceStatus.RUNNING:
            self.logger.debug("%s '%s' is already running", self.role, self.class_name)
            return

        self.logger.info("Running %s '%s'", self.role, self.class_name)
        self.status = ResourceStatus.RUNNING
        event = self._create_service_status_event(ResourceStatus.RUNNING)
        await self.hassette.send_event(event.topic, event)

    async def handle_starting(self) -> None:
        """Handle a starting event for the service."""

        if self.status == ResourceStatus.STARTING:
            self.logger.debug("%s '%s' is already starting", self.role, self.class_name)
            return

        self.logger.info("Starting %s '%s'", self.role, self.class_name)
        self.status = ResourceStatus.STARTING
        event = self._create_service_status_event(ResourceStatus.STARTING)
        await self.hassette.send_event(event.topic, event)

    async def handle_crash(self, exception: Exception) -> None:
        """Handle a crash event."""

        self.logger.exception("%s '%s' crashed", self.role, self.class_name)
        self.status = ResourceStatus.CRASHED
        event = self._create_service_status_event(ResourceStatus.CRASHED, exception)
        await self.hassette.send_event(event.topic, event)
        self.mark_not_ready("Crashed")

    async def cleanup(self) -> None:
        """Cleanup resources owned by the instance.

        This method is called during shutdown to ensure that all resources are properly released.
        """
        await self.task_bucket.cancel_all()
        self.logger.debug("Cleaned up resources for %s '%s'", self.role, self.class_name)


class Service(Resource):
    """Base class for services in the Hassette framework.

    A Service class or subclass represents a long-running entity within the Hassette framework,
    encapsulating its behavior and state. It is defined to offload lifecycle and status management
    from the individual service implementations.

    A Service is defined by having startup/shutdown logic and running indefinitely.
    """

    role: ClassVar[ResourceRole] = ResourceRole.SERVICE
    """Role of the service, e.g. 'App', 'Service', etc."""

    _task: asyncio.Task | None = None

    @abstractmethod
    async def run_forever(self) -> None:
        """Run the service indefinitely."""

        # we are not subclassing ABC to simplify the logic App has to use to find the
        # concrete class for it's Generic type parameter, so we raise NotImplementedError here
        raise NotImplementedError("Subclasses must implement run_forever method")

    def start(self) -> None:
        """Start the service."""
        if self._task and not self._task.done():
            raise RuntimeError(f"Service '{self.class_name}' is already running")
        self._task = self.task_bucket.spawn(self.run_forever(), name=f"service:run_forever_{self.class_name}")

    async def start_async_on_loop_thread(self) -> None:
        """Start the service asynchronously.

        Uses `run_on_loop_thread` to run the start method in the event loop.
        """
        await self.hassette.run_on_loop_thread(self.start)

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def shutdown(self, *args, **kwargs) -> None:
        """Shutdown the service.

        This method can be overridden by subclasses to perform service-specific shutdown tasks.
        """
        self.logger.debug("Shutting down '%s' %s", self.class_name, self.role)

        self.cancel()

        await self.handle_stop()
        self.status = ResourceStatus.STOPPED
