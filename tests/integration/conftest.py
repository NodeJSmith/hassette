"""Shared fixtures for integration tests."""

from contextlib import suppress
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from hassette import Hassette
from hassette.config.config import HassetteConfig
from hassette.test_utils.web_mocks import create_mock_runtime_query_service
from hassette.web.app import create_fastapi_app

if TYPE_CHECKING:
    from hassette.test_utils.harness import HassetteHarness


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


_HARNESS_FIXTURES = frozenset(
    {
        "hassette_with_nothing",
        "hassette_with_bus",
        "hassette_with_scheduler",
        "hassette_with_file_watcher",
        "hassette_with_state_proxy",
        "hassette_with_state_registry",
        "hassette_with_app_handler",
        # hassette_with_mock_api excluded: yields (Api, SimpleTestServer), not HassetteHarness.
        # hassette_with_app_handler_custom_config excluded: function-scoped, recreated fresh per test.
    }
)


@pytest.fixture(autouse=True)
async def cleanup_harness(request: pytest.FixtureRequest) -> None:
    """Reset all active module-scoped harness components before each test.

    Function-scoped fixtures (hassette_with_app_handler_custom_config)
    are recreated fresh per test and don't need cleanup.
    """
    for name in _HARNESS_FIXTURES & set(request.fixturenames):
        harness: HassetteHarness = request.getfixturevalue(name)
        await harness.reset()


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
