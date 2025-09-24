import asyncio
import contextlib
import typing
from collections.abc import Callable, Coroutine
from typing import Any, cast
from unittest.mock import PropertyMock, patch

import pytest
from aiohttp import web
from anyio import create_memory_object_stream
from yarl import URL

from hassette.core.api import Api, _Api
from hassette.core.bus.bus import Bus, _Bus
from hassette.core.classes import Resource
from hassette.core.core import Event, Hassette
from hassette.core.enums import ResourceStatus

from .test_server import SimpleTestServer

if typing.TYPE_CHECKING:
    from hassette.core.core import Hassette


@pytest.fixture(scope="module")
async def mock_hassette_with_bus():
    """Yields a mock Hassette instance with a running Bus. Everything else is a mock/AsyncMock."""

    class MockHassette:
        task: asyncio.Task

        def __init__(self):
            self._send_stream, self._receive_stream = create_memory_object_stream[tuple[str, Event]](1000)
            self._bus = _Bus(cast("Hassette", self), self._receive_stream.clone())
            self.bus = Bus(cast("Hassette", self), self._bus)
            self.ready_event = asyncio.Event()
            self.ready_event.set()

            self._resources: dict[str, Resource] = {}

        async def send_event(self, topic: str, event: Event[Any]) -> None:
            """Mock method to send an event to the bus."""
            await self._send_stream.send((topic, event))

        def create_task(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task:
            return asyncio.create_task(coro)

    hassette = MockHassette()

    hassette.task = asyncio.create_task(hassette._bus.run_forever())
    await asyncio.sleep(0.3)  # Allow the task to start
    yield hassette

    hassette.task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await hassette.task


async def _wait_for(
    predicate: Callable[[], bool],
    *,
    timeout: float = 3.0,
    interval: float = 0.02,
    desc: str = "condition",
) -> None:
    """Spin until predicate() is True or timeout."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        if predicate():
            return
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError(f"Timed out waiting for {desc}")
        await asyncio.sleep(interval)


async def _start_resource(res: Resource, *, desc: str) -> None:
    """Call .start() on a Resource and wait until RUNNING."""
    res.start()
    await _wait_for(lambda: getattr(res, "status", None) == ResourceStatus.RUNNING, desc=f"{desc} RUNNING")


async def _shutdown_resource(res: Resource, desc: str) -> None:
    """Gracefully shutdown a Resource, ignoring errors."""
    print(f"Shutting down {desc}...")
    with contextlib.suppress(Exception):
        await res.shutdown()


@pytest.fixture
async def mock_ha_api(unused_tcp_port, mock_hassette_with_bus):
    """
    Yields (api, mock) where:
      - api  is a fully started Api facade targeting a local in-proc HTTP server
      - mock is your expectation registry / handler
    """

    port = unused_tcp_port
    base_url = URL.build(scheme="http", host="127.0.0.1", port=port, path="/api/")

    mock = SimpleTestServer()

    # app/server
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", mock.handle_request)

    # Patches for _Api
    rest_url_patch = patch(
        "hassette.core.api._Api._rest_url",
        new_callable=PropertyMock,
        return_value=base_url,
    )
    headers_patch = patch(
        "hassette.core.api._Api._headers",
        new_callable=PropertyMock,
        return_value={"Authorization": "Bearer test_token"},
    )

    async with contextlib.AsyncExitStack() as stack:
        # start server
        runner = web.AppRunner(app)
        await runner.setup()

        site = web.TCPSite(runner, "127.0.0.1", port)
        await site.start()
        stack.push_async_callback(runner.cleanup)

        # apply patches
        stack.enter_context(rest_url_patch)
        stack.enter_context(headers_patch)

        # create API resources
        _api = _Api(mock_hassette_with_bus)
        api = Api(_api.hassette, _api)

        # start them
        await _start_resource(_api, desc="_Api")
        await asyncio.sleep(0.1)
        await _start_resource(api, desc="Api")
        await asyncio.sleep(0.1)

        try:
            yield api, mock
        finally:
            # orderly shutdown
            await _shutdown_resource(api, desc="Api")
            await _shutdown_resource(_api, desc="_Api")

    mock.assert_clean()
