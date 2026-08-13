"""Shared fixtures and helpers for web API integration tests."""

from unittest.mock import MagicMock

import pytest
from httpx2 import ASGITransport, AsyncClient

from hassette.schemas.app_snapshots import AppInstanceInfo, AppStatusSnapshot
from hassette.test_utils.config import TEST_SESSION_TTL, WEB_API_TEST_TOKEN
from hassette.test_utils.web_mocks import create_hassette_stub, create_mock_runtime_query_service
from hassette.types.enums import ResourceStatus
from hassette.web.app import create_fastapi_app

_SEED_TIMESTAMP = "2024-01-01T00:00:00"


@pytest.fixture
def mock_hassette():
    """Create a mock Hassette instance for the FastAPI app."""
    instance = AppInstanceInfo(
        app_key="my_app",
        index=0,
        instance_name="MyApp[0]",
        class_name="MyApp",
        status=ResourceStatus.RUNNING,
    )
    return create_hassette_stub(
        run_web_ui=False,
        states={
            "light.kitchen": {
                "entity_id": "light.kitchen",
                "state": "on",
                "attributes": {"brightness": 255},
                "last_changed": _SEED_TIMESTAMP,
                "last_updated": _SEED_TIMESTAMP,
            },
            "sensor.temp": {
                "entity_id": "sensor.temp",
                "state": "21.5",
                "attributes": {"unit_of_measurement": "°C"},
                "last_changed": _SEED_TIMESTAMP,
                "last_updated": _SEED_TIMESTAMP,
            },
        },
        old_snapshot=AppStatusSnapshot(instances=[instance]),
        app_action_mocks=True,
    )


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
    """Create an httpx2 AsyncClient for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def auth_hassette():
    """A `create_hassette_stub()` with `auth_enabled=True` and a real `session_ttl`.

    `create_hassette_stub()` doesn't set `session_ttl` on the MagicMock stub -- this fixture sets
    it directly so `verify_session_cookie`/`should_renew_session_cookie` (which do arithmetic
    against it) don't operate on an auto-generated `MagicMock` attribute.
    """
    hassette = create_hassette_stub(auth_enabled=True)
    hassette.config.web_api.session_ttl = TEST_SESSION_TTL
    create_mock_runtime_query_service(hassette)
    return hassette


@pytest.fixture
def auth_app(auth_hassette):
    """FastAPI app built with a known token, so bearer/cookie assertions have a concrete value."""
    return create_fastapi_app(auth_hassette, auth_token=WEB_API_TEST_TOKEN)


@pytest.fixture
async def auth_client(auth_app):
    transport = ASGITransport(app=auth_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def set_websocket_state(mock_hassette: MagicMock, *, connected: bool, ever_connected: bool) -> None:
    """Set the mock websocket service's connection state for system-status tests."""
    mock_hassette._websocket_service.is_connected = connected
    mock_hassette._websocket_service.has_ever_connected = ever_connected


def set_app_status_snapshot(
    mock_hassette: MagicMock,
    *,
    running: list[AppInstanceInfo] | None = None,
    failed: list[AppInstanceInfo] | None = None,
) -> None:
    """Set the mock AppHandler's live status snapshot — used to model pre-bootstrap (zero-app) state.

    RuntimeQueryService no longer depends on AppHandler, so the dashboard must serve a correct
    zero-app response before AppHandler finishes bootstrapping.
    """
    mock_hassette._app_handler.get_status_snapshot.return_value = AppStatusSnapshot(
        instances=(running or []) + (failed or [])
    )


def make_log_record(  # factory-local: timestamp=float(seq) is load-bearing for ordering tests
    seq: int,
    level: str = "INFO",
    message: str = "test",
    app_key: str | None = None,
    execution_id: str | None = None,
    source_tier: str | None = "framework",
) -> dict:
    return {
        "seq": seq,
        "timestamp": float(seq),
        "level": level,
        "logger_name": "hassette.test",
        "func_name": "test_func",
        "lineno": 1,
        "message": message,
        "exc_info": None,
        "app_key": app_key,
        "execution_id": execution_id,
        "instance_name": None,
        "instance_index": None,
        "source_tier": source_tier,
    }
