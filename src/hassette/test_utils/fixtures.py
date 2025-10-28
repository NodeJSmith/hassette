import contextlib
from typing import TYPE_CHECKING, cast

import pytest

from .harness import HassetteHarness

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from hassette import Api, Hassette, HassetteConfig
    from hassette.test_utils.test_server import SimpleTestServer


@contextlib.asynccontextmanager
async def _build_harness(**kwargs) -> "AsyncIterator[HassetteHarness]":
    harness = HassetteHarness(**kwargs)
    try:
        await harness.start()
        yield harness
    finally:
        await harness.stop()
        harness.config.reload()


@pytest.fixture(scope="module")
def hassette_harness(
    unused_tcp_port_factory,
) -> "Callable[..., contextlib.AbstractAsyncContextManager[HassetteHarness]]":
    def _factory(**kwargs) -> contextlib.AbstractAsyncContextManager[HassetteHarness]:
        return _build_harness(**kwargs, unused_tcp_port=unused_tcp_port_factory())

    return _factory


@pytest.fixture(scope="module")
async def hassette_with_nothing(
    hassette_harness: "Callable[..., contextlib.AbstractAsyncContextManager[HassetteHarness]]",
    test_config: "HassetteConfig",
) -> "AsyncIterator[Hassette]":
    async with hassette_harness(config=test_config) as harness:
        yield cast("Hassette", harness.hassette)


@pytest.fixture(scope="module")
async def hassette_with_bus(
    hassette_harness: "Callable[..., contextlib.AbstractAsyncContextManager[HassetteHarness]]",
    test_config: "HassetteConfig",
) -> "AsyncIterator[Hassette]":
    async with hassette_harness(config=test_config, use_bus=True) as harness:
        yield cast("Hassette", harness.hassette)


@pytest.fixture(scope="module")
async def hassette_with_mock_api(
    hassette_harness: "Callable[..., contextlib.AbstractAsyncContextManager[HassetteHarness]]",
    test_config: "HassetteConfig",
) -> "AsyncIterator[tuple[Api, SimpleTestServer]]":
    async with hassette_harness(config=test_config, use_bus=True, use_api_mock=True) as harness:
        assert harness.hassette.api is not None
        assert harness.api_mock is not None
        yield harness.hassette.api, harness.api_mock


@pytest.fixture(scope="module")
async def hassette_with_real_api(
    hassette_harness: "Callable[..., contextlib.AbstractAsyncContextManager[HassetteHarness]]",
    test_config: "HassetteConfig",
) -> "AsyncIterator[Hassette]":
    async with hassette_harness(config=test_config, use_bus=True, use_api_real=True, use_websocket=True) as harness:
        assert harness.hassette.api is not None
        yield cast("Hassette", harness.hassette)


@pytest.fixture(scope="module")
async def hassette_with_scheduler(
    hassette_harness: "Callable[..., contextlib.AbstractAsyncContextManager[HassetteHarness]]",
    test_config: "HassetteConfig",
) -> "AsyncIterator[Hassette]":
    async with hassette_harness(config=test_config, use_bus=True, use_scheduler=True) as harness:
        assert harness.hassette._scheduler is not None
        yield cast("Hassette", harness.hassette)


@pytest.fixture(scope="module")
async def hassette_with_file_watcher(
    hassette_harness: "Callable[..., contextlib.AbstractAsyncContextManager[HassetteHarness]]",
    test_config_with_apps,
) -> "AsyncIterator[Hassette]":
    config = test_config_with_apps
    config.file_watcher_debounce_milliseconds = 1
    config.file_watcher_step_milliseconds = 5

    async with hassette_harness(config=config, use_bus=True, use_file_watcher=True, use_api_mock=True) as harness:
        assert harness.hassette._file_watcher is not None
        assert harness.hassette._bus_service is not None

        yield cast("Hassette", harness.hassette)


@pytest.fixture
async def hassette_with_app_handler(
    hassette_harness: "Callable[..., contextlib.AbstractAsyncContextManager[HassetteHarness]]",
    test_config_with_apps,
) -> "AsyncIterator[Hassette]":
    # TODO: see if we can get this to be module scoped - currently fails
    # because there are config changes that persist between tests
    async with hassette_harness(
        config=test_config_with_apps,
        use_bus=True,
        use_app_handler=True,
        use_scheduler=True,
    ) as harness:
        yield cast("Hassette", harness.hassette)
