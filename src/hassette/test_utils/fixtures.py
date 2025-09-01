import asyncio
import contextlib
from collections.abc import Callable
from unittest.mock import AsyncMock, PropertyMock, patch

import pytest
from aiohttp import web
from yarl import URL

from hassette.core.api import Api, _Api
from hassette.core.classes import Resource
from hassette.core.enums import ResourceStatus

from .test_server import SimpleTestServer


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
async def mock_ha_api(unused_tcp_port):
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
        _api = _Api(AsyncMock())
        api = Api(_api.hassette, _api)

        # start them
        await _start_resource(_api, desc="_Api")
        await _start_resource(api, desc="Api")

        try:
            yield api, mock
        finally:
            # orderly shutdown
            await _shutdown_resource(api, desc="Api")
            await _shutdown_resource(_api, desc="_Api")

    mock.assert_clean()
