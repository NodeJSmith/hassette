"""Shared fixtures for integration tests."""

import pytest
from httpx import ASGITransport, AsyncClient

from hassette.test_utils.web_mocks import create_mock_data_sync_service
from hassette.web.app import create_fastapi_app

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
    from hassette.test_utils.reset import reset_state_proxy

    if "hassette_with_state_proxy" in request.fixturenames:
        try:
            hassette = request.getfixturevalue("hassette_with_state_proxy")
            if hassette._state_proxy is not None:
                await reset_state_proxy(hassette._state_proxy)
        except Exception:
            pass


@pytest.fixture(autouse=True)
async def cleanup_bus_fixture(request: pytest.FixtureRequest):
    """Automatically remove all bus listeners before each test.

    Covers fixtures that include a Bus: hassette_with_bus, hassette_with_scheduler,
    hassette_with_file_watcher, and hassette_with_state_registry.
    """
    from hassette.test_utils.reset import reset_bus

    for name in _BUS_FIXTURES & set(request.fixturenames):
        try:
            hassette = request.getfixturevalue(name)
            if hassette._bus is not None:
                await reset_bus(hassette._bus)
                break
        except Exception:
            pass


@pytest.fixture(autouse=True)
async def cleanup_scheduler_fixture(request: pytest.FixtureRequest):
    """Automatically remove all scheduler jobs before each test."""
    from hassette.test_utils.reset import reset_scheduler

    if "hassette_with_scheduler" in request.fixturenames:
        try:
            hassette = request.getfixturevalue("hassette_with_scheduler")
            if hassette._scheduler is not None:
                await reset_scheduler(hassette._scheduler)
        except Exception:
            pass


@pytest.fixture(autouse=True)
async def cleanup_mock_api_fixture(request: pytest.FixtureRequest):
    """Automatically clear mock API expectations before each test."""
    from hassette.test_utils.reset import reset_mock_api

    if "hassette_with_mock_api" in request.fixturenames:
        try:
            _, server = request.getfixturevalue("hassette_with_mock_api")
            reset_mock_api(server)
        except Exception:
            pass


@pytest.fixture
def data_sync_service(mock_hassette):
    """Create a DataSyncService with mocked Hassette."""
    return create_mock_data_sync_service(mock_hassette)


@pytest.fixture
def app(mock_hassette, data_sync_service):  # noqa: ARG001
    """Create a FastAPI app with mocked dependencies."""
    return create_fastapi_app(mock_hassette)


@pytest.fixture
async def client(app):
    """Create an httpx AsyncClient for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
