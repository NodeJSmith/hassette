import asyncio
import contextlib
import logging
import threading
import typing
from collections.abc import Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, cast
from unittest.mock import AsyncMock, Mock, PropertyMock, patch

from aiohttp import web
from anyio import create_memory_object_stream
from yarl import URL

from hassette import HassetteConfig
from hassette.core import context
from hassette.core.resources.api import Api
from hassette.core.resources.base import Resource, _HassetteBase
from hassette.core.resources.bus.bus import Bus
from hassette.core.resources.scheduler.scheduler import Scheduler
from hassette.core.resources.tasks import TaskBucket, make_task_factory
from hassette.core.services.api_service import _ApiService
from hassette.core.services.app_handler import _AppHandler
from hassette.core.services.bus_service import _BusService
from hassette.core.services.file_watcher import _FileWatcher
from hassette.core.services.scheduler_service import _SchedulerService
from hassette.core.services.websocket_service import _Websocket
from hassette.enums import ResourceStatus
from hassette.events import Event
from hassette.test_utils.test_server import SimpleTestServer
from hassette.utils.service_utils import wait_for_ready

if typing.TYPE_CHECKING:
    from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

    from hassette.core.core import Hassette


async def wait_for(
    predicate: Callable[[], bool], *, timeout: float = 3.0, interval: float = 0.02, desc: str = "condition"
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        if predicate():
            return
        if loop.time() >= deadline:
            raise TimeoutError(f"Timed out waiting for {desc}")
        await asyncio.sleep(interval)


async def start_resource(res: Resource, *, desc: str) -> asyncio.Task[Any] | None:
    res.start()
    task: asyncio.Task[Any] | None = None
    if hasattr(res, "get_task"):
        task = res.get_task()
    await wait_for(lambda: getattr(res, "status", None) == ResourceStatus.RUNNING, desc=f"{desc} RUNNING")
    return task


async def shutdown_resource(res: Resource, *, desc: str) -> None:  # noqa
    with contextlib.suppress(Exception):
        await res.shutdown()


class _HassetteMock(_HassetteBase):
    task_bucket: TaskBucket

    def __init__(self, *, config: HassetteConfig) -> None:
        self.config = config

        self.ready_event = asyncio.Event()
        self.shutdown_event = asyncio.Event()
        self._resources: dict[str, Resource] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread_id: int | None = None
        self._thread_pool: ThreadPoolExecutor | None = None
        self._send_stream: MemoryObjectSendStream[tuple[str, Event[Any]]] | None = None
        self._receive_stream: MemoryObjectReceiveStream[tuple[str, Event[Any]]] | None = None

        self._api_service: _ApiService | None = None
        self.api: Api | None = None
        self._bus_service: _BusService | None = None
        self._bus: Bus | None = None
        self._scheduler_service: _SchedulerService | None = None
        self._scheduler: Scheduler | None = None
        self._file_watcher: _FileWatcher | None = None
        self._app_handler: _AppHandler | None = None
        self._websocket: _Websocket | None = None

        self.unique_id = "hassette-mock"
        self.unique_name = "Hassette Mock Instance"

    async def send_event(self, topic: str, event: Event[Any]) -> None:
        if not self._send_stream:
            raise RuntimeError("Bus is not enabled on this harness")
        if self._send_stream._closed:
            raise RuntimeError("Event bus send stream is closed")
        await self._send_stream.send((topic, event))

    def run_sync(self, fn: Coroutine, timeout_seconds: int | None = 2):
        """Run an async function in a synchronous context.

        Args:
            fn (Coroutine[Any, Any, R]): The async function to run.
            timeout_seconds (int | None): The timeout for the function call, defaults to 1, to use the config value.

        Returns:
            R: The result of the function call.

        """

        timeout_seconds = timeout_seconds

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

    def create_task(self, coro: Coroutine[Any, Any, Any], name: str) -> asyncio.Task[Any]:
        return self.task_bucket.spawn(coro, name=name)

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        if not self._loop:
            raise RuntimeError("Event loop is not running")
        return self._loop

    async def run_on_loop_thread(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if not self._loop:
            raise RuntimeError("Event loop is not running")
        fut: asyncio.Future[Any] = self._loop.create_future()

        def _call() -> None:
            try:
                fut.set_result(fn(*args, **kwargs))
            except Exception as exc:  # pragma: no cover
                fut.set_exception(exc)

        self._loop.call_soon_threadsafe(_call)
        return await fut

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

    def get_app(self, name: str, index: int = 0) -> Any:
        if not self._app_handler:
            raise RuntimeError("App handler is not enabled on this harness")
        return self._app_handler.get(name, index=index)


@dataclass
class HassetteHarness:
    config: HassetteConfig
    use_bus: bool = False
    use_scheduler: bool = False
    use_api_mock: bool = False
    use_api_real: bool = False
    use_file_watcher: bool = False
    use_app_handler: bool = False
    use_websocket: bool = False
    unused_tcp_port: int = 0

    def __post_init__(self) -> None:
        # need this for caplog to work properly
        logging.getLogger("hassette").propagate = True

        if self.use_api_mock and self.use_api_real:
            raise ValueError("Cannot use both API mock and real API in the same harness")

        self.logger = logging.getLogger(f"hassette.test.harness.{type(self).__name__}")
        self.hassette = _HassetteMock(config=self.config)
        self._tasks: list[tuple[str, asyncio.Task[Any]]] = []
        self._exit_stack = contextlib.AsyncExitStack()
        self._thread_pool: ThreadPoolExecutor | None = None
        self.api_mock: SimpleTestServer | None = None
        self.api_base_url = URL.build(scheme="http", host="127.0.0.1", port=self.unused_tcp_port, path="/api/")

        context.HASSETTE_CONFIG.set(self.config)
        context.HASSETTE_INSTANCE.set(cast("Hassette", self.hassette))

    async def __aenter__(self):
        await self.start()

        assert self.hassette._loop is not None, "Event loop is not running"
        assert self.hassette._loop.is_running(), "Event loop is not running"
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.stop()

    async def start(self) -> "HassetteHarness":
        self.hassette._loop = asyncio.get_running_loop()
        self.hassette._loop_thread_id = threading.get_ident()
        self.hassette._thread_pool = self._thread_pool = ThreadPoolExecutor(thread_name_prefix="hassette-test-worker-")
        self.hassette.task_bucket = TaskBucket(
            cast("Hassette", self.hassette), name="hassette", unique_name_prefix="hassette"
        )
        self.hassette._loop.set_task_factory(make_task_factory(self.hassette.task_bucket))

        if self.use_bus:
            await self._start_bus()
        if self.use_scheduler:
            await self._start_scheduler()
        if self.use_file_watcher:
            await self._start_file_watcher()
        if self.use_api_mock:
            await self._start_api_mock()

        # if self.use_api_real:
        #     await self.start_api_real()
        if self.use_app_handler:
            await self._start_app_handler()
        # if self.use_websocket:
        #     await self.start_websocket()

        if not self.hassette._api_service:
            self.hassette._api_service = Mock()

        if not self.hassette.api:
            self.hassette.api = AsyncMock()
            self.hassette.api.sync = Mock()

        self.hassette.ready_event.set()
        await wait_for_ready(
            [x for x in self.hassette._resources.values()], timeout=1, shutdown_event=self.hassette.shutdown_event
        )

        return self

    async def stop(self) -> None:
        self.hassette.shutdown_event.set()

        try:
            for name, resource in reversed(self.hassette._resources.items()):
                print(f"Shutting down resource: {name} ({resource})")
                await shutdown_resource(resource, desc=name)
                await asyncio.sleep(0.05)
        except Exception:
            self.logger.exception("Error shutting down resources")

        try:
            for _, task in reversed(self._tasks):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        except Exception:
            self.logger.exception("Error cancelling tasks")

        try:
            if self.api_mock is not None:
                self.api_mock.assert_clean()
        except Exception:
            self.logger.exception("Error checking API mock")

        await self._exit_stack.aclose()

        if self._thread_pool is not None:
            self._thread_pool.shutdown(wait=True)
            self._thread_pool = None
            self.hassette._thread_pool = None
        self.hassette._loop = None

    async def _start_bus(self) -> None:
        send_stream, receive_stream = create_memory_object_stream[tuple[str, Event[Any]]](1000)
        self.hassette._send_stream = send_stream
        self.hassette._receive_stream = receive_stream
        bus_service = _BusService(cast("Hassette", self.hassette), receive_stream.clone())

        self._exit_stack.push_async_callback(send_stream.aclose)
        self._exit_stack.push_async_callback(receive_stream.aclose)

        self.hassette._bus_service = bus_service
        self.hassette._bus = Bus(cast("Hassette", self.hassette), owner="Hassette")
        self.hassette._resources[Bus.class_name] = self.hassette._bus
        self.hassette._resources[_BusService.class_name] = bus_service
        bus_service.start()
        self.hassette._bus.start()

    async def _start_scheduler(self) -> None:
        scheduler_service = _SchedulerService(cast("Hassette", self.hassette))
        scheduler = Scheduler(cast("Hassette", self.hassette), owner="Hassette")
        self.hassette._scheduler_service = scheduler_service
        self.hassette._scheduler = scheduler
        self.hassette._thread_pool = self._thread_pool
        self.hassette._resources[_SchedulerService.class_name] = scheduler_service
        self.hassette._resources[Scheduler.class_name] = scheduler
        scheduler_service.start()
        scheduler.start()

    async def _start_file_watcher(self) -> None:
        if not self.hassette.config:
            raise RuntimeError("File watcher requires a config")
        watcher = _FileWatcher(cast("Hassette", self.hassette))
        self.hassette._file_watcher = watcher
        self.hassette._resources[_FileWatcher.class_name] = watcher
        watcher.start()

    async def _start_app_handler(self) -> None:
        if not self.use_bus:
            raise RuntimeError("App handler requires bus")

        app_handler = _AppHandler(cast("Hassette", self.hassette))
        self.hassette._app_handler = app_handler
        self.hassette._resources[_AppHandler.class_name] = app_handler
        self.hassette._websocket = Mock()
        self.hassette._websocket.status = ResourceStatus.RUNNING
        app_handler.start()

        return

    async def _start_api_mock(self) -> None:
        if not self.api_base_url:
            raise RuntimeError("API harness requires api_base_url")
        mock_server = SimpleTestServer()
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", mock_server.handle_request)

        runner = web.AppRunner(app)
        await runner.setup()
        self._exit_stack.push_async_callback(runner.cleanup)

        site = web.TCPSite(runner, self.api_base_url.host or "127.0.0.1", self.api_base_url.port or 80)
        await site.start()
        self._exit_stack.push_async_callback(site.stop)

        rest_url_patch = patch(
            "hassette.core.services.api_service._ApiService._rest_url",
            new_callable=PropertyMock,
            return_value=self.api_base_url,
        )
        headers_patch = patch(
            "hassette.core.services.api_service._ApiService._headers",
            new_callable=PropertyMock,
            return_value={"Authorization": "Bearer test_token"},
        )
        self._exit_stack.enter_context(rest_url_patch)
        self._exit_stack.enter_context(headers_patch)

        self.hassette._websocket = Mock(spec=_Websocket)
        self.hassette._websocket.ready_event = asyncio.Event()
        self.hassette._websocket.ready_event.set()

        self.hassette._api_service = _ApiService(cast("Hassette", self.hassette))

        self.hassette.api = api = Api(self.hassette._api_service.hassette)
        self.hassette._resources[_ApiService.class_name] = self.hassette._api_service
        self.hassette._resources[Api.class_name] = api

        self.api_mock = mock_server

        self.hassette._api_service.start()
        self.hassette.api.start()

        return
