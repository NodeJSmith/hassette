import asyncio
import threading
import typing
from typing import Any, ParamSpec, TypeVar

from anyio import create_memory_object_stream

from hassette.config import HassetteConfig
from hassette.utils.app_utils import run_apps_pre_check
from hassette.utils.exception_utils import get_traceback_string
from hassette.utils.service_utils import wait_for_ready

from . import context
from .resources.api.api import Api
from .resources.base import Resource, Service
from .resources.bus.bus import Bus
from .resources.scheduler.scheduler import Scheduler
from .resources.tasks import TaskBucket, make_task_factory
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


class Hassette(Resource):
    """Main class for the Hassette application.

    This class initializes the Hassette instance, manages services, and provides access to the API,
    event bus, app handler, and other core components.
    """

    api: Api
    """API service for handling HTTP requests."""

    @property
    def unique_name(self) -> str:
        return "Hassette"

    def __init__(self, config: HassetteConfig) -> None:
        """
        Initialize the Hassette instance.

        Args:
            env_file (str | Path | None): Path to the environment file for configuration.
            config (HassetteConfig | None): Optional pre-loaded configuration.
        """
        self.config = config
        run_apps_pre_check(self.config)

        self.unique_id = ""
        super().__init__(self, task_bucket=TaskBucket.create(self, self), parent=self)

        self._send_stream, self._receive_stream = create_memory_object_stream[tuple[str, "Event"]](1000)

        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread_id: int | None = None

        # private background services
        self._bus_service = self.add_child(_BusService, stream=self._receive_stream.clone())

        self._service_watcher = self.add_child(_ServiceWatcher)
        self._websocket = self.add_child(_Websocket)
        self._health_service = self.add_child(_HealthService)
        self._file_watcher = self.add_child(_FileWatcher)
        self._app_handler = self.add_child(_AppHandler)
        self._scheduler_service = self.add_child(_SchedulerService)

        self._api_service = self.add_child(_ApiService)

        # internal instances
        self._bus = self.add_child(Bus)
        self._scheduler = self.add_child(Scheduler)
        self.api = self.add_child(Api)

        # set context variable
        context.HASSETTE_INSTANCE.set(self)

        self.logger.info("All components registered...")

    @property
    def event_streams_closed(self) -> bool:
        """Check if the event streams are closed."""
        return self._send_stream._closed and self._receive_stream._closed

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

        inst = context.HASSETTE_INSTANCE.get(None)
        if inst is not None:
            return inst

        raise RuntimeError(
            "Hassette is not initialized in the current context. Use `Hassette.run_forever()` to start it."
        )

    async def send_event(self, event_name: str, event: "Event[Any]") -> None:
        """Send an event to the event bus."""
        await self._send_stream.send((event_name, event))

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

        self.loop.set_task_factory(make_task_factory(self.task_bucket))

        self._start_resources()

        self.logger.info("Waiting for resources to initialize...")

        self.ready_event.set()

        started = await self.wait_for_ready(list(self.children), timeout=self.config.startup_timeout_seconds)

        if not started:
            not_ready_resources = [r.class_name for r in self.children if not r.is_ready()]
            self.logger.error("The following resources failed to start: %s", ", ".join(not_ready_resources))
            self.logger.error("Not all resources started successfully, shutting down")
            await self.shutdown()
            return

        self.logger.info("All resources started successfully")
        self.logger.info("Hassette is running.")

        if self.shutdown_event.is_set():
            self.logger.warning("Hassette is shutting down, aborting run loop")
            await self.shutdown()

        try:
            await self.shutdown_event.wait()
        except asyncio.CancelledError:
            self.logger.debug("Hassette run loop cancelled")
        except Exception as e:
            self.logger.error("Error in Hassette run loop: %s", e)
        finally:
            await self.shutdown()

        self.logger.info("Hassette stopped.")

    def _start_resources(self) -> None:
        """Start background services like websocket, event bus, and scheduler."""

        for service in self.children:
            service.start()

    async def on_shutdown(self) -> None:
        """Shutdown all services gracefully and gather any results."""

        shutdown_tasks = [resource.shutdown() for resource in reversed(self.children)]

        self.logger.info("Waiting for all resources to finish...")

        results = await asyncio.gather(*shutdown_tasks, return_exceptions=True)

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
