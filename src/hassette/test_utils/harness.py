import asyncio
import contextlib
import logging
import tracemalloc
import typing
from collections.abc import Callable, Coroutine, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, cast
from unittest.mock import PropertyMock, patch

from aiohttp import web
from anyio import create_memory_object_stream

from hassette.core.api import Api, _Api
from hassette.core.apps.app_handler import _AppHandler
from hassette.core.bus.bus import Bus, BusService
from hassette.core.classes import Resource
from hassette.core.core import Event, Hassette
from hassette.core.enums import ResourceStatus
from hassette.core.file_watcher import _FileWatcher
from hassette.core.scheduler.scheduler import Scheduler, SchedulerService
from hassette.core.websocket import _Websocket
from hassette.test_utils.test_server import SimpleTestServer

if typing.TYPE_CHECKING:
    from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
    from yarl import URL

LOGGER = logging.getLogger(__name__)
tracemalloc.start()


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


class _HarnessHassette:
    def __init__(self, *, config: Any | None = None) -> None:
        self.config = config
        self.logger = logging.getLogger("hassette.test.harness")
        self.ready_event = asyncio.Event()
        self.ready_event.set()
        self._shutdown_event = asyncio.Event()
        self._resources: dict[str, Resource] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread_pool: ThreadPoolExecutor | None = None
        self._send_stream: MemoryObjectSendStream[tuple[str, Event[Any]]] | None = None
        self._receive_stream: MemoryObjectReceiveStream[tuple[str, Event[Any]]] | None = None

        self._api: _Api | None = None
        self.api: Api | None = None
        self.bus_service: BusService | None = None
        self._bus: Bus | None = None
        self.scheduler_service: SchedulerService | None = None
        self._scheduler: Scheduler | None = None
        self._file_watcher: _FileWatcher | None = None
        self._app_handler: _AppHandler | None = None
        self._websocket: _Websocket | None = None

    async def send_event(self, topic: str, event: Event[Any]) -> None:
        if not self._send_stream:
            raise RuntimeError("Bus is not enabled on this harness")
        if self._send_stream._closed:
            raise RuntimeError("Event bus send stream is closed")
        await self._send_stream.send((topic, event))

    def create_task(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        if not self._loop:
            raise RuntimeError("Event loop is not running")
        return self._loop.create_task(coro)

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

    async def wait_for_resources_running(
        self,
        resources: Iterable[Resource] | Resource,
        *,
        poll_interval: float = 0.1,
        timeout: int = 5,
    ) -> bool:
        from hassette.utils import wait_for_resources_running_or_raise

        if isinstance(resources, Resource) or not isinstance(resources, Iterable):
            resources = [resources]
        try:
            await wait_for_resources_running_or_raise(list(resources), timeout=timeout, poll_interval=poll_interval)
            return True
        except TimeoutError:
            return False

    async def get_app(self, name: str, index: int = 0) -> Any:
        if not self._app_handler:
            raise RuntimeError("App handler is not enabled on this harness")
        return self._app_handler.get(name, index=index)


@dataclass
class HassetteHarness:
    config: Any | None = None
    use_bus: bool = False
    use_scheduler: bool = False
    use_api: bool = False
    use_file_watcher: bool = False
    use_app_handler: bool = False
    api_base_url: "URL | None" = None

    def __post_init__(self) -> None:
        if self.use_api or self.use_file_watcher or self.use_scheduler or self.use_app_handler:
            self.use_bus = True
        self.hassette = _HarnessHassette(config=self.config)
        self._tasks: list[tuple[str, asyncio.Task[Any]]] = []
        self._resources: list[tuple[str, Resource]] = []
        self._exit_stack = contextlib.AsyncExitStack()
        self._previous_instance: Hassette | None = None
        self._thread_pool: ThreadPoolExecutor | None = None

        self.api: Api | None = None
        self.api_mock: SimpleTestServer | None = None
        self._scheduler: SchedulerService | None = None
        self.scheduler: Scheduler | None = None
        self._file_watcher: _FileWatcher | None = None
        self._bus: BusService | None = None
        self.bus: Bus | None = None
        self._app_handler: _AppHandler | None = None
        self._websocket: _Websocket | None = None

    async def __aenter__(self) -> "HassetteHarness":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.stop()

    async def start(self) -> "HassetteHarness":
        self.hassette._loop = asyncio.get_running_loop()
        self._thread_pool = ThreadPoolExecutor()
        self.hassette._thread_pool = self._thread_pool
        self._previous_instance = getattr(Hassette, "_instance", None)
        Hassette._instance = cast("Hassette", self.hassette)

        if self.use_bus:
            await self._start_bus()
        if self.use_scheduler:
            await self._start_scheduler()
        if self.use_file_watcher:
            await self._start_file_watcher()
        if self.use_api:
            await self._start_api()
        if self.use_app_handler:
            await self._start_app_handler()

        return self

    async def stop(self) -> None:
        self.hassette._shutdown_event.set()

        try:
            for name, resource in reversed(self._resources):
                await shutdown_resource(resource, desc=name)
        except Exception:
            LOGGER.exception("Error shutting down resources")

        try:
            for _, task in reversed(self._tasks):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        except Exception:
            LOGGER.exception("Error cancelling tasks")

        try:
            if self.api_mock is not None:
                self.api_mock.assert_clean()
        except Exception:
            LOGGER.exception("Error checking API mock")

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
        bus_service = BusService(cast("Hassette", self.hassette), receive_stream.clone())

        self._exit_stack.push_async_callback(send_stream.aclose)
        self._exit_stack.push_async_callback(receive_stream.aclose)

        self.hassette.bus_service = bus_service
        self.hassette._bus = Bus(cast("Hassette", self.hassette), owner="Hassette")
        self.hassette._resources[BusService.class_name] = bus_service
        self.hassette._resources[Bus.class_name] = self.hassette._bus
        task = await start_resource(bus_service, desc="BusService")
        if task:
            self._tasks.append(("BusService", task))

    async def _start_scheduler(self) -> None:
        scheduler_service = SchedulerService(cast("Hassette", self.hassette))
        scheduler = Scheduler(cast("Hassette", self.hassette), owner="Hassette")
        self.hassette.scheduler_service = scheduler_service
        self.hassette._scheduler = scheduler
        self.hassette._thread_pool = self._thread_pool
        self.hassette._resources[SchedulerService.class_name] = scheduler_service
        self.hassette._resources[Scheduler.class_name] = scheduler
        scheduler_service.max_delay = 1
        task = await start_resource(scheduler_service, desc="SchedulerService")
        if task:
            self._tasks.append(("SchedulerService", task))

    async def _start_file_watcher(self) -> None:
        if not self.hassette.config:
            raise RuntimeError("File watcher requires a config")
        watcher = _FileWatcher(cast("Hassette", self.hassette))
        self.hassette._file_watcher = watcher
        self.hassette._resources[_FileWatcher.class_name] = watcher
        task = await start_resource(watcher, desc="_FileWatcher")
        if task:
            self._tasks.append(("_FileWatcher", task))

    async def _start_app_handler(self) -> None:
        if not self.hassette._bus:
            raise RuntimeError("App handler requires bus")
        app_handler = _AppHandler(cast("Hassette", self.hassette))
        self.hassette._app_handler = app_handler
        self.hassette._resources[_AppHandler.class_name] = app_handler
        self.hassette._websocket = _Websocket(cast("Hassette", self.hassette))
        self.hassette._websocket.status = ResourceStatus.RUNNING
        self.hassette._resources[_Websocket.class_name] = self.hassette._websocket
        await app_handler.initialize()

        return

    async def _start_api(self) -> None:
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
            "hassette.core.api._Api._rest_url", new_callable=PropertyMock, return_value=self.api_base_url
        )
        headers_patch = patch(
            "hassette.core.api._Api._headers",
            new_callable=PropertyMock,
            return_value={"Authorization": "Bearer test_token"},
        )
        self._exit_stack.enter_context(rest_url_patch)
        self._exit_stack.enter_context(headers_patch)

        api_service = _Api(cast("Hassette", self.hassette))
        api = Api(api_service.hassette, api_service)
        self.hassette._api = api_service
        self.hassette.api = api
        self.hassette._resources[_Api.class_name] = api_service
        self.hassette._resources[Api.class_name] = api

        task_service = await start_resource(api_service, desc="_Api")
        if task_service:
            self._tasks.append(("_Api", task_service))
        task_api = await start_resource(api, desc="Api")
        if task_api:
            self._tasks.append(("Api", task_api))
        self.api = api
        self.api_mock = mock_server
        self._resources.append(("_Api", api_service))
        self._resources.append(("Api", api))

        return
