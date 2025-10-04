import asyncio
import typing
import uuid
from asyncio import Future, ensure_future
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from logging import getLogger
from typing import Any, ClassVar, ParamSpec, TypeVar

from anyio import create_memory_object_stream

from ..config import HassetteConfig
from ..utils import get_traceback_string, wait_for_resources_running
from .api import Api, _Api
from .apps.app_handler import _AppHandler
from .bus.bus import Bus, _BusService
from .classes import Resource, Service
from .enums import ResourceRole
from .events import Event
from .file_watcher import _FileWatcher
from .health_service import _HealthService
from .scheduler.scheduler import Scheduler, _SchedulerService
from .service_watcher import _ServiceWatcher
from .websocket import _Websocket

P = ParamSpec("P")
R = TypeVar("R")

T = TypeVar("T", bound=Resource | Service)


class Hassette:
    """Main class for the Hassette application.

    This class initializes the Hassette instance, manages services, and provides access to the API,
    event bus, app handler, and other core components.
    """

    role: ClassVar[ResourceRole] = ResourceRole.CORE

    _instance: ClassVar["Hassette"] = None  # type: ignore

    api: Api
    """API service for handling HTTP requests."""

    ready_event: asyncio.Event
    """Event set when the application is ready to accept requests."""

    shutdown_event: asyncio.Event
    """Event set when the application is starting to shutdown."""

    @property
    def unique_name(self) -> str:
        """Unique identifier for the instance."""
        return f"{type(self).__name__}-{self.unique_id}"

    def __init__(self, config: HassetteConfig) -> None:
        """
        Initialize the Hassette instance.

        Args:
            env_file (str | Path | None): Path to the environment file for configuration.
            config (HassetteConfig | None): Optional pre-loaded configuration.
        """
        self.unique_id = uuid.uuid4().hex

        self.logger = getLogger(__name__)

        self.config = config

        # collections
        self._resources: dict[str, Resource | Service] = {}

        self.ready_event: asyncio.Event = asyncio.Event()
        self.shutdown_event: asyncio.Event = asyncio.Event()

        self._send_stream, self._receive_stream = create_memory_object_stream[tuple[str, Event]](1000)

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread_pool = ThreadPoolExecutor(max_workers=10)

        # private background services
        self._service_watcher = self._register_resource(_ServiceWatcher)
        self._websocket = self._register_resource(_Websocket)
        self._api = self._register_resource(_Api)
        self._health_service = self._register_resource(_HealthService)
        self._file_watcher = self._register_resource(_FileWatcher)
        self._app_handler = self._register_resource(_AppHandler)
        self._scheduler_service = self._register_resource(_SchedulerService)
        self._bus_service = self._register_resource(_BusService, self._receive_stream.clone())

        # public services
        self.api = self._register_resource(Api, self._api)

        # internal instances
        self._bus = self._register_resource(Bus, self.unique_name)
        self._scheduler = self._register_resource(Scheduler, self.unique_name)

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

    async def send_event(self, event_name: str, event: Event[Any]) -> None:
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

        timeout_seconds = timeout_seconds or self.config.run_sync_timeout_seconds

        # If we're already in an event loop, don't allow blocking calls.
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass  # not in a loop -> safe to block
        else:
            fn.close()  # close the coroutine to avoid warnings
            raise RuntimeError("This sync method was called from within an event loop. Use the async method instead.")

        try:
            if self._loop is None:
                raise RuntimeError("Event loop is not running")

            fut = asyncio.run_coroutine_threadsafe(fn, self._loop)
            return fut.result(timeout=timeout_seconds)
        except TimeoutError:
            self.logger.exception("Sync function '%s' timed out", fn.__name__)
            raise
        except Exception:
            self.logger.exception("Failed to run sync function '%s'", fn.__name__)
            raise
        finally:
            if not fut.done():
                fut.cancel()

    async def run_on_loop_thread(self, fn: typing.Callable[..., R], *args, **kwargs) -> R:
        """Run a synchronous function on the main event loop thread.

        This is useful for ensuring that loop-affine code runs in the correct context.
        """
        if not self._loop:
            raise RuntimeError("Event loop is not running")

        fut = self._loop.create_future()

        def _call():
            try:
                fut.set_result(fn(*args, **kwargs))
            except Exception as e:
                fut.set_exception(e)

        self._loop.call_soon_threadsafe(_call)
        return await fut

    def create_task(self, coro: Coroutine[Any, Any, R], name: str) -> asyncio.Task[R]:
        """Create a task in the main event loop.

        Args:
            coro (Coroutine[Any, Any, R]): The coroutine to run as a task.

        Returns:
            asyncio.Task[R]: The created task.
        """
        return self.loop.create_task(coro, name=name)

    async def wait_for_ready(
        self,
        resources: list[Resource] | Resource,
        poll_interval: float = 0.1,
        timeout: int = 20,
    ) -> bool:
        """Block until all dependent resources are ready or shutdown is requested.

        Args:
            resources (list[Resource] | Resource): The resources to wait for.
            poll_interval (float): The interval to poll for resource status.
            timeout (int): The timeout for the wait operation.

        Returns:
            bool: True if all resources are ready, False if timeout or shutdown.

        Raises:
            CancelledError: If the wait operation is cancelled.
            TimeoutError: If the wait operation times out.
        """

        resources = resources if isinstance(resources, list) else [resources]
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            if self.shutdown_event.is_set():
                return False
            if all(r.is_ready() for r in resources):
                return True
            if asyncio.get_event_loop().time() >= deadline:
                return False
            await asyncio.sleep(poll_interval)

    async def wait_for_resources_running(
        self, resources: list[Resource] | Resource, poll_interval: float = 0.1, timeout: int = 20
    ) -> bool:
        """Block until all dependent resources are running or shutdown is requested.

        Args:
            resources (list[Resource] | Resource): The resources to wait for.
            poll_interval (float): The interval to poll for resource status.
            timeout (int): The timeout for the wait operation.
        Returns:
            bool: True if all resources are running, False if timeout or shutdown.
        """
        resources = resources if isinstance(resources, list) else [resources]

        return await wait_for_resources_running(
            resources,
            poll_interval=poll_interval,
            timeout=timeout,
            shutdown_event=self.shutdown_event,
        )

    async def run_forever(self) -> None:
        """Start Hassette and run until shutdown signal is received."""
        self._loop = asyncio.get_running_loop()
        self._start_resources()

        self.ready_event.set()

        started = await self.wait_for_ready(list(self._resources.values()), timeout=self.config.startup_timeout_seconds)

        if not started:
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
            except Exception as e:
                self.logger.error("Failed to shutdown resource '%s': %s", resource.class_name, e)

        self.logger.info("Waiting for all resources to finish...")

        tasks = [task for s in self._resources.values() if (task := s.get_task())]
        gather_tasks: list[Future] = []
        for t in tasks:
            try:
                gather_tasks.append(ensure_future(t))
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

    def shutdown(self) -> None:
        """Signal shutdown to the main loop."""
        self.logger.debug("Shutting down Hassette")
        self.shutdown_event.set()
