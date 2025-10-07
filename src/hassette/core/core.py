import asyncio
import threading
import typing
from asyncio import Future, ensure_future
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import Any, ClassVar, ParamSpec, TypeVar

from anyio import create_memory_object_stream

from hassette.config import HassetteConfig
from hassette.enums import ResourceRole
from hassette.utils.exception_utils import get_traceback_string
from hassette.utils.service_utils import wait_for_ready

from .resources import Api, Bus, Resource, Scheduler, Service, TaskBucket, make_task_factory
from .resources.base import _LoggerMixin
from .services.api_service import _ApiService
from .services.app_handler import _AppHandler
from .services.bus_service import _BusService
from .services.file_watcher import _FileWatcher
from .services.health_service import _HealthService
from .services.scheduler_service import _SchedulerService
from .services.service_watcher import _ServiceWatcher
from .services.websocket_service import _Websocket

if typing.TYPE_CHECKING:
    from hassette.events import Event

P = ParamSpec("P")
R = TypeVar("R")

T = TypeVar("T", bound=Resource | Service)


class Hassette(_LoggerMixin):
    """Main class for the Hassette application.

    This class initializes the Hassette instance, manages services, and provides access to the API,
    event bus, app handler, and other core components.
    """

    role: ClassVar[ResourceRole] = ResourceRole.CORE

    api: Api
    """API service for handling HTTP requests."""

    ready_event: asyncio.Event
    """Event set when the application is ready to accept requests."""

    shutdown_event: asyncio.Event
    """Event set when the application is starting to shutdown."""

    _instance: ClassVar["Hassette"] = None  # type: ignore

    def __init__(self, config: HassetteConfig) -> None:
        """
        Initialize the Hassette instance.

        Args:
            env_file (str | Path | None): Path to the environment file for configuration.
            config (HassetteConfig | None): Optional pre-loaded configuration.
        """
        super().__init__(unique_name_prefix="Hassette")

        self.config = config
        TaskBucket.default_task_cancellation_timeout = self.config.task_cancellation_timeout_seconds

        # collections
        self._resources: dict[str, Resource | Service] = {}

        self.ready_event: asyncio.Event = asyncio.Event()
        self.shutdown_event: asyncio.Event = asyncio.Event()

        self._send_stream, self._receive_stream = create_memory_object_stream[tuple[str, "Event"]](1000)

        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread_id: int | None = None
        self._thread_pool = ThreadPoolExecutor(max_workers=10, thread_name_prefix="hassette-worker-")

        # private background services
        self._service_watcher = self._register_resource(_ServiceWatcher)
        self._websocket = self._register_resource(_Websocket)
        self._health_service = self._register_resource(_HealthService)
        self._file_watcher = self._register_resource(_FileWatcher)
        self._app_handler = self._register_resource(_AppHandler)
        self._scheduler_service = self._register_resource(_SchedulerService)
        self._bus_service = self._register_resource(_BusService, self._receive_stream.clone())
        self._api_service = self._register_resource(_ApiService)

        # internal instances
        self._bus = self._register_resource(Bus, self.unique_name)
        self._scheduler = self._register_resource(Scheduler, self.unique_name)
        self.api = self._register_resource(Api, self.unique_name)

        type(self)._instance = self

    def _register_resource(self, resource: type[T], *args) -> T:
        """Register a service with the Hassette instance."""

        if resource.class_name in self._resources:
            raise ValueError(f"{resource.role} '{resource.class_name}' is already registered in Hassette")

        self._resources[resource.class_name] = inst = resource(self, *args)
        return inst

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        """Get the current event loop."""
        if self._loop is None:
            raise RuntimeError("Event loop is not running")
        return self._loop

    @property
    def apps(self):
        """Get the currently loaded apps."""
        # note: return type left deliberately empty to allow underlying call to define it
        return self._app_handler.apps

    def get_app(self, app_name: str, index: int = 0):
        """Get a specific app instance if running.

        Args:
            app_name (str): The name of the app.
            index (int): The index of the app instance, defaults to 0.

        Returns:
            App[AppConfig] | None: The app instance if found, else None.
        """
        # note: return type left deliberately empty to allow underlying call to define it

        return self._app_handler.get(app_name, index)

    @classmethod
    def get_instance(cls) -> "Hassette":
        """Get the current instance of Hassette."""

        if cls._instance is not None:
            return cls._instance

        raise RuntimeError(
            "Hassette is not initialized in the current context. Use `Hassette.run_forever()` to start it."
        )

    async def send_event(self, event_name: str, event: "Event[Any]") -> None:
        """Send an event to the event bus."""
        await self._send_stream.send((event_name, event))

    def run_sync(self, fn: Coroutine[Any, Any, R], timeout_seconds: int | None = None) -> R:
        """Run an async function in a synchronous context.

        Args:
            fn (Coroutine[Any, Any, R]): The async function to run.
            timeout_seconds (int | None): The timeout for the function call, defaults to 0, to use the config value.

        Returns:
            R: The result of the function call.
        """
        return self._global_tasks.run_sync(fn, timeout_seconds=timeout_seconds)

    async def run_on_loop_thread(self, fn: typing.Callable[..., R], *args, **kwargs) -> R:
        """Run a synchronous function on the main event loop thread.

        This is useful for ensuring that loop-affine code runs in the correct context.
        """
        return await self._global_tasks.run_on_loop_thread(fn, *args, **kwargs)

    def create_task(self, coro: Coroutine[Any, Any, R], name: str) -> asyncio.Task[R]:
        """Create a task tracked in the global hassette task bucket.

        Args:
            coro (Coroutine[Any, Any, R]): The coroutine to run as a task.

        Returns:
            asyncio.Task[R]: The created task.
        """

        return self._global_tasks.spawn(coro, name=name)

    async def wait_for_ready(self, resources: list[Resource] | Resource, timeout: int | None = None) -> bool:
        """Block until all dependent resources are ready or shutdown is requested.

        Args:
            resources (list[Resource] | Resource): The resource(s) to wait for.
            timeout (int): The timeout for the wait operation.

        Returns:
            bool: True if all resources are ready, False if shutdown is requested.
        """
        timeout = timeout or self.config.startup_timeout_seconds

        return await wait_for_ready(resources, timeout=timeout, shutdown_event=self.shutdown_event)

    async def run_forever(self) -> None:
        """Start Hassette and run until shutdown signal is received."""
        self._loop = asyncio.get_running_loop()
        self._loop_thread_id = threading.get_ident()
        self.loop.set_debug(self.config.dev_mode)

        self._global_tasks = TaskBucket(self, name="hassette", prefix="hassette")
        self.loop.set_task_factory(make_task_factory(self._global_tasks))

        self._start_resources()

        self.ready_event.set()

        started = await self.wait_for_ready(list(self._resources.values()), timeout=self.config.startup_timeout_seconds)

        if not started:
            not_ready_resources = [r.class_name for r in self._resources.values() if not r.is_ready()]
            self.logger.error("The following resources failed to start: %s", ", ".join(not_ready_resources))
            self.logger.error("Not all resources started successfully, shutting down")
            await self._shutdown()
            return

        self.logger.info("All resources started successfully")
        self.logger.info("Hassette is running.")

        if self.shutdown_event.is_set():
            self.logger.warning("Hassette is shutting down, aborting run loop")
            await self._shutdown()

        try:
            await self.shutdown_event.wait()
        except asyncio.CancelledError:
            self.logger.debug("Hassette run loop cancelled")
        except Exception as e:
            self.logger.error("Error in Hassette run loop: %s", e)
        finally:
            await self._shutdown()

        self.logger.info("Hassette stopped.")

    def _start_resources(self) -> None:
        """Start background services like websocket, event bus, and scheduler."""

        for service in self._resources.values():
            service.start()

    async def _shutdown(self) -> None:
        """Shutdown all services gracefully and gather any results."""
        self.shutdown()  # signal shutdown

        # shutdown each resource
        for resource in reversed(self._resources.values()):
            try:
                await resource.shutdown()

                # in case the resource does not call its own cleanup
                # shouldn't happen, but be safe
                await resource.cleanup()
            except Exception as e:
                self.logger.error("Failed to shutdown resource '%s': %s", resource.class_name, e)

        self.logger.info("Waiting for all resources to finish...")

        tasks = [task for s in self._resources.values() if (task := s.get_task())]
        gather_tasks: list[Future] = []
        for t in tasks:
            try:
                gather_tasks.append(ensure_future(t, loop=self.loop))
            except Exception as e:
                self.logger.error("Failed to ensure future for task '%s': %s", t, e)

        results = await asyncio.gather(*gather_tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                self.logger.error("Task raised an exception: %s", get_traceback_string(result))
            else:
                self.logger.debug("Task completed successfully: %s", result)

        # ensure streams are closed
        if self._send_stream is not None:
            await self._send_stream.aclose()
        if self._receive_stream is not None:
            await self._receive_stream.aclose()

        await self._global_tasks.cancel_all()

    def shutdown(self) -> None:
        """Signal shutdown to the main loop."""
        self.logger.debug("Shutting down Hassette")
        self.shutdown_event.set()
