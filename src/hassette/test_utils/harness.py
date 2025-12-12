import asyncio
import contextlib
import logging
import threading
import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast
from unittest.mock import AsyncMock, Mock, PropertyMock, patch

from aiohttp import web
from anyio import create_memory_object_stream
from yarl import URL

from hassette import HassetteConfig, context
from hassette.api import Api
from hassette.bus import Bus
from hassette.core.api_resource import ApiResource
from hassette.core.app_handler import AppHandler
from hassette.core.bus_service import BusService
from hassette.core.file_watcher import FileWatcherService
from hassette.core.scheduler_service import SchedulerService
from hassette.core.state_proxy import StateProxy
from hassette.core.state_registry import STATE_REGISTRY, StateRegistry
from hassette.core.type_registry import TYPE_REGISTRY, TypeRegistry
from hassette.core.websocket_service import WebsocketService
from hassette.events import Event
from hassette.resources.base import Resource
from hassette.scheduler import Scheduler
from hassette.state_manager import StateManager
from hassette.task_bucket import TaskBucket, make_task_factory
from hassette.test_utils.test_server import SimpleTestServer
from hassette.types.enums import ResourceStatus
from hassette.utils.service_utils import wait_for_ready
from hassette.utils.url_utils import build_rest_url, build_ws_url

if typing.TYPE_CHECKING:
    from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

    from hassette import Hassette


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
    task = res.task
    await wait_for(lambda: getattr(res, "status", None) == ResourceStatus.RUNNING, desc=f"{desc} RUNNING")
    return task


async def shutdown_resource(res: Resource) -> None:
    with contextlib.suppress(Exception):
        await res.shutdown()


class _HassetteMock(Resource):
    task_bucket: TaskBucket

    def __init__(self, *, config: HassetteConfig) -> None:
        self.config = config
        super().__init__(cast("Hassette", self))

        self.ready_event = asyncio.Event()
        self.shutdown_event = asyncio.Event()
        self.children: list[Resource] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread_id: int | None = None
        self._send_stream: MemoryObjectSendStream[tuple[str, Event[Any]]] | None = None
        self._receive_stream: MemoryObjectReceiveStream[tuple[str, Event[Any]]] | None = None

        self._api_service: ApiResource | None = None
        self.api: Api | None = None
        self._bus_service: BusService | None = None
        self._bus: Bus | None = None
        self._scheduler_service: SchedulerService | None = None
        self._scheduler: Scheduler | None = None
        self._file_watcher: FileWatcherService | None = None
        self._app_handler: AppHandler | None = None
        self._websocket_service: WebsocketService | None = None
        self._state_proxy: StateProxy | None = None
        self._states: StateManager | None = None
        self.state_registry: StateRegistry | None = None
        self.type_registry: TypeRegistry | None = None

    @property
    def ws_url(self) -> str:
        """Construct the WebSocket URL for Home Assistant."""
        return build_ws_url(self.config)

    @property
    def rest_url(self) -> str:
        """Construct the REST API URL for Home Assistant."""
        return build_rest_url(self.config)

    async def send_event(self, topic: str, event: Event[Any]) -> None:
        if not self._send_stream:
            raise RuntimeError("Bus is not enabled on this harness")
        if self._send_stream._closed:
            raise RuntimeError("Event bus send stream is closed")
        await self._send_stream.send((topic, event))

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        if not self._loop:
            raise RuntimeError("Event loop is not running")
        return self._loop

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

    def get_app(self, name: str, index: int = 0) -> Any:
        if not self._app_handler:
            raise RuntimeError("App handler is not enabled on this harness")
        return self._app_handler.get(name, index=index)

    @property
    def event_streams_closed(self) -> bool:
        """Check if the event streams are closed."""
        if not self._send_stream or not self._receive_stream:
            return True
        return self._send_stream._closed and self._receive_stream._closed


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
    use_state_proxy: bool = False
    use_state_registry: bool = False
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
        self.api_mock: SimpleTestServer | None = None
        self.api_base_url = URL.build(scheme="http", host="127.0.0.1", port=self.unused_tcp_port, path="/api/")

        context.set_global_hassette(cast("Hassette", self.hassette))

        self.config.set_validated_app_manifests()

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
        self.hassette.task_bucket = TaskBucket.create(cast("Hassette", self.hassette), parent=self.hassette)  # pyright: ignore[reportArgumentType]
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
            if not self.use_state_proxy:
                await self._start_state_proxy()
        # if self.use_websocket:
        #     await self.start_websocket()

        # Set up API and websocket mocks before state proxy if needed
        if not self.hassette._api_service:
            self.hassette._api_service = Mock()
            self.hassette._api_service.ready_event = asyncio.Event()
            self.hassette._api_service.ready_event.set()

        if not self.hassette._websocket_service:
            self.hassette._websocket_service = Mock()
            self.hassette._websocket_service.ready_event = asyncio.Event()
            self.hassette._websocket_service.ready_event.set()

        if not self.hassette.api:
            self.hassette.api = AsyncMock()
            self.hassette.api.sync = Mock()

        if self.use_state_proxy:
            if not self.use_bus:
                raise RuntimeError("State proxy requires bus")
            await self._start_state_proxy()

        if self.use_state_registry:
            self.hassette.state_registry = STATE_REGISTRY
            self.hassette.type_registry = TYPE_REGISTRY

        self.hassette._states = self.hassette.add_child(StateManager)

        if not self.use_bus:
            self.hassette.send_event = AsyncMock()

        for resource in self.hassette.children:
            resource.start()

        self.hassette.ready_event.set()
        await wait_for_ready(
            [x for x in self.hassette.children], timeout=1, shutdown_event=self.hassette.shutdown_event
        )

        return self

    async def stop(self) -> None:
        self.hassette.shutdown_event.set()

        try:
            for resource in self.hassette.children:
                await shutdown_resource(resource)
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

        self.hassette._loop = None

    async def _start_bus(self) -> None:
        send_stream, receive_stream = create_memory_object_stream[tuple[str, Event[Any]]](1000)
        self.hassette._send_stream = send_stream
        self.hassette._receive_stream = receive_stream

        self.hassette._bus_service = self.hassette.add_child(BusService, stream=receive_stream.clone())
        self.hassette._bus = self.hassette.add_child(Bus)

        self._exit_stack.push_async_callback(send_stream.aclose)
        self._exit_stack.push_async_callback(receive_stream.aclose)

    async def _start_scheduler(self) -> None:
        self.hassette._scheduler_service = self.hassette.add_child(SchedulerService)
        self.hassette._scheduler = self.hassette.add_child(Scheduler)

    async def _start_file_watcher(self) -> None:
        if not self.hassette.config:
            raise RuntimeError("File watcher requires a config")

        self.hassette._file_watcher = self.hassette.add_child(FileWatcherService)

    async def _start_app_handler(self) -> None:
        if not self.use_bus:
            raise RuntimeError("App handler requires bus")

        self.hassette._app_handler = self.hassette.add_child(AppHandler)
        self.hassette._websocket_service = Mock()
        self.hassette._websocket_service.status = ResourceStatus.RUNNING

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
            "hassette.core.api_resource.ApiResource._rest_url",
            new_callable=PropertyMock,
            return_value=self.api_base_url,
        )
        headers_patch = patch(
            "hassette.core.api_resource.ApiResource._headers",
            new_callable=PropertyMock,
            return_value={"Authorization": "Bearer test_token"},
        )
        self._exit_stack.enter_context(rest_url_patch)
        self._exit_stack.enter_context(headers_patch)

        self.hassette._websocket_service = Mock(spec=WebsocketService)
        self.hassette._websocket_service.ready_event = asyncio.Event()
        self.hassette._websocket_service.ready_event.set()

        self.hassette._api_service = self.hassette.add_child(ApiResource)
        self.hassette.api = self.hassette.add_child(Api)

        self.api_mock = mock_server

        return

    async def _start_state_proxy(self) -> None:
        if not self.use_bus:
            raise RuntimeError("State proxy requires bus")

        self.hassette._state_proxy = self.hassette.add_child(StateProxy)
        return
