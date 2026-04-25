"""Shared fixtures for integration tests."""

from contextlib import suppress
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from hassette import Hassette
from hassette.config.config import HassetteConfig
from hassette.test_utils.reset import reset_bus, reset_mock_api, reset_scheduler, reset_state_proxy

if TYPE_CHECKING:
    from hassette.test_utils.harness import HassetteHarness
from hassette.test_utils.web_mocks import create_mock_runtime_query_service
from hassette.web.app import create_fastapi_app


@pytest.fixture
async def hassette_instance(test_config: HassetteConfig):
    """Provide a fresh Hassette instance and restore context afterwards."""
    test_config.reload()
    instance = Hassette(test_config)
    instance.wire_services()
    try:
        yield instance
    finally:
        with suppress(Exception):
            if not instance._event_stream_service.event_streams_closed:
                await instance._event_stream_service.close_streams()

        with suppress(Exception):
            if not instance._bus_service.stream._closed:
                await instance._bus_service.stream.aclose()


_BUS_FIXTURES = frozenset(
    {
        "hassette_with_bus",
        "hassette_with_scheduler",
        "hassette_with_file_watcher",
        "hassette_with_state_registry",
    }
)


@pytest.fixture(autouse=True)
async def cleanup_state_proxy_fixture(request: pytest.FixtureRequest):
    """Automatically reset state proxy before each test when using hassette_with_state_proxy.

    This autouse fixture resets the state proxy BEFORE each test to ensure a clean state.
    It only resets if the test actually uses the hassette_with_state_proxy fixture.
    """
    if "hassette_with_state_proxy" in request.fixturenames:
        harness: HassetteHarness = request.getfixturevalue("hassette_with_state_proxy")
        if harness.has_component("state_proxy"):
            await reset_state_proxy(harness.state_proxy)


@pytest.fixture(autouse=True)
async def cleanup_bus_fixture(request: pytest.FixtureRequest):
    """Automatically remove all bus listeners before each test.

    Covers fixtures that include a Bus: hassette_with_bus, hassette_with_scheduler,
    hassette_with_file_watcher, and hassette_with_state_registry.
    """
    for name in _BUS_FIXTURES & set(request.fixturenames):
        harness: HassetteHarness = request.getfixturevalue(name)
        if harness.has_component("bus"):
            await reset_bus(harness.bus)
            break


@pytest.fixture(autouse=True)
async def cleanup_scheduler_fixture(request: pytest.FixtureRequest):
    """Automatically remove all scheduler jobs before each test."""
    if "hassette_with_scheduler" in request.fixturenames:
        harness: HassetteHarness = request.getfixturevalue("hassette_with_scheduler")
        if harness.has_component("scheduler"):
            await reset_scheduler(harness.scheduler)


@pytest.fixture(autouse=True)
async def cleanup_mock_api_fixture(request: pytest.FixtureRequest):
    """Automatically clear mock API expectations before each test."""
    if "hassette_with_mock_api" in request.fixturenames:
        _, server = request.getfixturevalue("hassette_with_mock_api")
        reset_mock_api(server)


@pytest.fixture
def runtime_query_service(mock_hassette):
    """Create a RuntimeQueryService with mocked Hassette."""
    return create_mock_runtime_query_service(mock_hassette)


@pytest.fixture
def app(mock_hassette, runtime_query_service):  # noqa: ARG001
    """Create a FastAPI app with mocked dependencies."""
    return create_fastapi_app(mock_hassette)


@pytest.fixture
async def client(app):
    """Create an httpx AsyncClient for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
