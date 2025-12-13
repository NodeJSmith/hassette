import asyncio
import threading
import typing
from typing import Any, ParamSpec, TypeVar

from anyio import create_memory_object_stream
from dotenv import load_dotenv

from hassette import context
from hassette.api import Api
from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.bus import Bus
from hassette.config import HassetteConfig
from hassette.exceptions import AppPrecheckFailedError
from hassette.logging_ import enable_logging
from hassette.resources.base import Resource, Service
from hassette.scheduler import Scheduler
from hassette.state_manager import StateManager
from hassette.task_bucket import TaskBucket, make_task_factory
from hassette.utils.app_utils import run_apps_pre_check
from hassette.utils.exception_utils import get_traceback_string
from hassette.utils.service_utils import wait_for_ready
from hassette.utils.url_utils import build_rest_url, build_ws_url

from .api_resource import ApiResource
from .app_handler import AppHandler
from .bus_service import BusService
from .file_watcher import FileWatcherService
from .health_service import HealthService
from .scheduler_service import SchedulerService
from .service_watcher import ServiceWatcher
from .state_proxy import StateProxy
from .state_registry import STATE_REGISTRY, StateRegistry
from .type_registry import TYPE_REGISTRY, TypeRegistry
from .websocket_service import WebsocketService

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

    states: StateManager
    """States manager instance for accessing Home Assistant states."""

    state_registry: StateRegistry
    """State registry for managing state class registrations and conversions."""

    type_registry: TypeRegistry
    """Type registry for managing state value type conversions."""

    @property
    def unique_name(self) -> str:
        return "Hassette"

    def __init__(self, config: HassetteConfig) -> None:
        self.config = config

        self.unique_id = ""
        enable_logging(self.config.log_level)
        super().__init__(self, task_bucket=TaskBucket.create(self, self), parent=self)

        # set context variables
        context.set_global_hassette(self)
        context.set_global_hassette_config(self.config)

        self._startup_tasks()

        self._send_stream, self._receive_stream = create_memory_object_stream[tuple[str, "Event"]](1000)

        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread_id: int | None = None

        # private background services
        self._bus_service = self.add_child(BusService, stream=self._receive_stream.clone())

        self._service_watcher = self.add_child(ServiceWatcher)
        self._websocket_service = self.add_child(WebsocketService)
        self._health_service = self.add_child(HealthService)
        self._file_watcher = self.add_child(FileWatcherService)
        self._app_handler = self.add_child(AppHandler)
        self._scheduler_service = self.add_child(SchedulerService)

        self._api_service = self.add_child(ApiResource)
        self._state_proxy = self.add_child(StateProxy)

        # internal instances
        self._bus = self.add_child(Bus)
        self._scheduler = self.add_child(Scheduler)

        # public instances
        self.states = self.add_child(StateManager)
        self.api = self.add_child(Api)
        self.state_registry = STATE_REGISTRY
        self.type_registry = TYPE_REGISTRY

        self.logger.info("All components registered...")

    def _startup_tasks(self):
        """Perform one-time startup tasks.

        These were originally on the `HassetteConfig` class but we do not want these called
        when the config is reloaded, only on initial startup.
        """
        # one time startup tasks
        if self.config.import_dot_env_files:
            for env_file in self.config.env_files:
                if env_file.exists():
                    self.logger.debug("Loading environment variables from %s", env_file)
                    load_dotenv(env_file)

        self.config.set_validated_app_manifests()

        active_apps = [app for app in self.config.app_manifests.values() if app.enabled]
        if active_apps:
            self.logger.info("Active apps: %s", active_apps)
        else:
            self.logger.info("No active apps found.")

        inactive_apps = [app for app in self.config.app_manifests.values() if not app.enabled]
        if inactive_apps:
            self.logger.info("Inactive apps: %s", inactive_apps)

        if self.config.run_app_precheck:
            try:
                run_apps_pre_check(self.config)
            except AppPrecheckFailedError:
                if not self.config.allow_startup_if_app_precheck_fails:
                    self.logger.error("App precheck failed and startup is not allowed to continue. Raising exception.")
                    raise
                self.logger.warning("App precheck failed, but startup will continue due to configuration setting.")

    @property
    def ws_url(self) -> str:
        """Construct the WebSocket URL for Home Assistant."""
        return build_ws_url(self.config)

    @property
    def rest_url(self) -> str:
        """Construct the REST API URL for Home Assistant."""
        return build_rest_url(self.config)

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
    def apps(self) -> dict[str, dict[int, App[AppConfig]]]:
        """Get the currently loaded apps."""
        # note: return type left deliberately empty to allow underlying call to define it
        return self._app_handler.apps

    def get_app(self, app_name: str, index: int = 0) -> App[AppConfig] | None:
        """Get a specific app instance if running.

        Args:
            app_name: The name of the app.
            index: The index of the app instance, defaults to 0.

        Returns:
            App[AppConfig] | None: The app instance if found, else None.
        """
        # note: return type left deliberately empty to allow underlying call to define it

        return self._app_handler.get(app_name, index)

    @classmethod
    def get_instance(cls) -> "Hassette":
        """Get the current instance of Hassette."""

        return context.get_hassette()

    async def send_event(self, event_name: str, event: "Event[Any]") -> None:
        """Send an event to the event bus."""
        await self._send_stream.send((event_name, event))

    async def wait_for_ready(self, resources: list[Resource] | Resource, timeout: int | None = None) -> bool:
        """Block until all dependent resources are ready or shutdown is requested.

        Args:
            resources: The resource(s) to wait for.
            timeout: The timeout for the wait operation.

        Returns:
            True if all resources are ready, False if shutdown is requested.
        """
        timeout = timeout or self.config.startup_timeout_seconds

        return await wait_for_ready(resources, timeout=timeout, shutdown_event=self.shutdown_event)

    async def run_forever(self) -> None:
        """Start Hassette and run until shutdown signal is received."""
        self._loop = asyncio.get_running_loop()
        self._loop_thread_id = threading.get_ident()
        self.loop.set_debug(self.config.asyncio_debug_mode)

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

        # does not take into consideration if apps failed to load, but those errors would have been logged already
        self.logger.info("All services started successfully.")
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
