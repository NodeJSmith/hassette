import contextlib
from typing import TYPE_CHECKING, cast

import pytest
from yarl import URL

from .harness import HassetteHarness

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from hassette.config.core_config import HassetteConfig
    from hassette.core.api import Api
    from hassette.core.core import Hassette
    from hassette.core.scheduler import Scheduler
    from hassette.test_utils.test_server import SimpleTestServer


@contextlib.asynccontextmanager
async def _build_harness(**kwargs) -> "AsyncIterator[HassetteHarness]":
    harness = HassetteHarness(**kwargs)
    try:
        await harness.start()
        yield harness
    finally:
        await harness.stop()


@pytest.fixture(scope="module")
def hassette_harness() -> "Callable[..., contextlib.AbstractAsyncContextManager[HassetteHarness]]":
    def _factory(**kwargs) -> contextlib.AbstractAsyncContextManager[HassetteHarness]:
        return _build_harness(**kwargs)

    return _factory


@pytest.fixture
async def hassette_with_bus(
    hassette_harness: "Callable[..., contextlib.AbstractAsyncContextManager[HassetteHarness]]",
) -> "AsyncIterator[Hassette]":
    async with hassette_harness(use_bus=True) as harness:
        yield cast("Hassette", harness.hassette)


@pytest.fixture
async def hassette_with_mock_api(
    unused_tcp_port: int,
    hassette_harness: "Callable[..., contextlib.AbstractAsyncContextManager[HassetteHarness]]",
) -> "AsyncIterator[tuple[Api, SimpleTestServer]]":
    port = unused_tcp_port
    base_url = URL.build(scheme="http", host="127.0.0.1", port=port, path="/api/")

    async with hassette_harness(use_bus=True, use_api_mock=True, api_base_url=base_url) as harness:
        assert harness.hassette.api is not None
        assert harness.api_mock is not None
        yield harness.hassette.api, harness.api_mock


@pytest.fixture
async def hassette_with_real_api(
    hassette_harness: "Callable[..., contextlib.AbstractAsyncContextManager[HassetteHarness]]",
    test_config: "HassetteConfig",
) -> "AsyncIterator[Hassette]":
    async with hassette_harness(config=test_config, use_bus=True, use_api_real=True, use_websocket=True) as harness:
        assert harness.hassette.api is not None
        yield cast("Hassette", harness.hassette)


@pytest.fixture
async def hassette_scheduler(
    hassette_harness: "Callable[..., contextlib.AbstractAsyncContextManager[HassetteHarness]]",
    test_config: "HassetteConfig",
) -> "AsyncIterator[Scheduler]":
    async with hassette_harness(config=test_config, use_scheduler=True) as harness:
        assert harness.hassette._scheduler is not None
        yield harness.hassette._scheduler


@pytest.fixture
async def hassette_with_file_watcher(
    hassette_harness: "Callable[..., contextlib.AbstractAsyncContextManager[HassetteHarness]]",
    test_config_with_apps,
) -> "AsyncIterator[Hassette]":
    config = test_config_with_apps
    config.file_watcher_debounce_milliseconds = 1
    config.file_watcher_step_milliseconds = 5

    async with hassette_harness(config=config, use_bus=True, use_file_watcher=True) as harness:
        assert harness.hassette._file_watcher is not None
        assert harness.hassette.bus_service is not None

        yield cast("Hassette", harness.hassette)


@pytest.fixture
async def hassette_with_app_handler(
    hassette_harness: "Callable[..., contextlib.AbstractAsyncContextManager[HassetteHarness]]",
    test_config_with_apps,
) -> "AsyncIterator[Hassette]":
    async with hassette_harness(
        config=test_config_with_apps, use_bus=True, use_app_handler=True, use_scheduler=True, use_websocket=True
    ) as harness:
        yield cast("Hassette", harness.hassette)

    # # TODO: get this working with fake api
    # # need to handle websocket dependency and assert_clean call of mock_api
    # port = unused_tcp_port
    # base_url = URL.build(scheme="http", host="127.0.0.1", port=port, path="/api/")

    # async with hassette_harness(
    #     config=test_config_with_apps,
    #     use_bus=True,
    #     use_app_handler=True,
    #     use_scheduler=True,
    #     use_api_mock=True,
    #     api_base_url=base_url,
    # ) as harness:
    #     yield cast("Hassette", harness.hassette)
