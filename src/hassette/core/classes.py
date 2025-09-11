import asyncio
import copy
import logging
import typing
from abc import abstractmethod
from logging import getLogger
from typing import ClassVar

from hassette.core.enums import ResourceRole, ResourceStatus
from hassette.core.events import create_service_status_event

if typing.TYPE_CHECKING:
    from hassette.core.core import Hassette


class _HassetteBase:
    logger: ClassVar[logging.Logger]
    """Logger for the class."""

    class_name: ClassVar[str]
    """Name of the class."""

    role: ClassVar[ResourceRole] = ResourceRole.BASE
    """Role of the resource, e.g. 'App', 'Service', etc."""

    status: ResourceStatus = ResourceStatus.NOT_STARTED
    """Current status of the resource."""

    def __init__(self, hassette: "Hassette", *args, **kwargs) -> None:
        """
        Initialize the class with a reference to the Hassette instance.

        Args:
            hassette (Hassette): The Hassette instance this resource belongs to.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.
        """
        self.hassette = hassette

    def __init_subclass__(cls) -> None:
        """
        Initialize the subclass with a logger.

        This method is called when a subclass is created, setting up a logger
        for the class based on its module and name.
        """
        cls.class_name = cls.__name__
        cls.logger = getLogger(f"{cls.__module__}.{cls.__name__}")

    def set_logger_to_debug(self) -> None:
        """Configure a logger to log DEBUG independently of its parent."""
        self.logger.setLevel(logging.DEBUG)
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
                handler.setLevel(logging.DEBUG)
                self.logger.addHandler(handler)

    def _create_service_status_event(self, status: ResourceStatus, exception: Exception | None = None):
        return create_service_status_event(
            resource_name=self.class_name,
            role=self.role,
            status=status,
            previous_status=self.status,
            exc=exception,
        )

    async def handle_stop(self) -> None:
        """Handle a stop event."""

        self.logger.info("Stopping %s '%s'", self.role, self.class_name)
        self.status = ResourceStatus.STOPPED
        event = self._create_service_status_event(ResourceStatus.STOPPED)
        await self.hassette.send_event(event.topic, event)

    async def handle_failed(self, exception: Exception) -> None:
        """Handle a failure event."""

        self.logger.error("%s '%s' failed: %s - %s", self.role, self.class_name, type(exception), str(exception))
        self.status = ResourceStatus.FAILED
        event = self._create_service_status_event(ResourceStatus.FAILED, exception)
        await self.hassette.send_event(event.topic, event)

    async def handle_start(self) -> None:
        """Handle a start event for the service."""

        self.logger.info("Starting %s '%s'", self.role, self.class_name)
        self.status = ResourceStatus.RUNNING
        event = self._create_service_status_event(ResourceStatus.RUNNING)
        await self.hassette.send_event(event.topic, event)

    async def handle_crash(self, exception: Exception) -> None:
        """Handle a crash event."""

        self.logger.exception("%s '%s' crashed", self.role, self.class_name)
        self.status = ResourceStatus.CRASHED
        event = self._create_service_status_event(ResourceStatus.CRASHED, exception)
        await self.hassette.send_event(event.topic, event)


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

    _task: asyncio.Task | None = None

    def __init__(self, hassette: "Hassette", *args, **kwargs) -> None:
        """
        Initialize the resource.

        Args:
            hassette (Hassette): The Hassette instance this resource belongs to.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.
        """
        super().__init__(hassette, *args, **kwargs)
        self.logger.debug("Creating instance of '%s' %s", self.class_name, self.role)

    def start(self) -> None:
        """Start the resource."""
        if self.status != ResourceStatus.NOT_STARTED:
            self.logger.warning("%s '%s' is already started or running", self.role, self.class_name)
            return

        self.logger.debug("Starting '%s' %s", self.class_name, self.role)
        self._task = self.hassette.create_task(self.initialize())

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
        await self.handle_start()

    async def shutdown(self, *args, **kwargs) -> None:
        """Shutdown the resource.

        This method can be overridden by subclasses to perform resource-specific shutdown tasks.
        """
        if self.status == ResourceStatus.STOPPED:
            self.logger.warning("%s '%s' is already stopped", self.role, self.class_name)
            return

        self.logger.debug("Shutting down '%s' %s", self.class_name, self.role)
        await self.handle_stop()
        self.status = ResourceStatus.STOPPED

    async def restart(self) -> None:
        """Restart the resource."""
        self.logger.debug("Restarting '%s' %s", self.class_name, self.role)
        await self.shutdown()
        await self.initialize()


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
        self._task = self.hassette.create_task(self.run_forever())

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
