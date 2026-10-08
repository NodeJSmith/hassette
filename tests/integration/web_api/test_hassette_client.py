"""``hassette_client`` against the real FastAPI app on a real uvicorn socket.

The client's own tests use a fake server; these prove the transport, error mapping and parsing agree
with what hassette actually serves.
"""

from collections.abc import AsyncIterator, Iterator
from importlib.metadata import version
from pathlib import Path
from unittest.mock import MagicMock

import aiohttp
import pytest
from hassette_client import (
    AppNotFoundError,
    AuthenticationError,
    HassetteClient,
    NotFoundError,
    TelemetryUnavailableError,
    UnexpectedResponseError,
    check_server_version,
)
from hassette_wire import ProblemCode

from hassette.testing.config import WEB_API_TEST_TOKEN
from hassette.web.app import create_fastapi_app
from tests.integration.web_api.conftest import telemetry_error
from tests.support.uvicorn import start_uvicorn_server, stop_uvicorn_server

# `app`, `auth_app`, `mock_hassette` and `stub_spa` come from this directory's conftest.py.


@pytest.fixture
def server_url(app) -> Iterator[str]:
    server, thread, port = start_uvicorn_server(app)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        stop_uvicorn_server(server, thread)


@pytest.fixture
def auth_server_url(auth_app) -> Iterator[str]:
    server, thread, port = start_uvicorn_server(auth_app)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        stop_uvicorn_server(server, thread)


@pytest.fixture
def spa_server_url(mock_hassette: MagicMock, stub_spa: Path) -> Iterator[str]:
    """A server whose SPA catch-all answers every path outside ``/api`` with the web UI's HTML."""
    del stub_spa  # only needed for its side effect: SPA files for the catch-all to serve
    mock_hassette.config.web_api.run_ui = True
    server, thread, port = start_uvicorn_server(create_fastapi_app(mock_hassette))
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        stop_uvicorn_server(server, thread)


@pytest.fixture
async def session() -> AsyncIterator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession() as client_session:
        yield client_session


async def test_same_checkout_server_passes_the_version_check(session: aiohttp.ClientSession, server_url: str) -> None:
    """Server and client are released together, so a same-checkout server is never below the minimum."""
    health = await HassetteClient(session, server_url).get_health()

    assert health.version == version("hassette")
    check_server_version(health)


async def test_liveness_round_trips(session: aiohttp.ClientSession, server_url: str) -> None:
    assert (await HassetteClient(session, server_url).get_liveness()).status == "live"


async def test_base_url_with_an_extra_api_segment_raises_not_found(
    session: aiohttp.ClientSession, server_url: str
) -> None:
    """Every request becomes ``/api/api/...``, which the server answers with its routing problem."""
    with pytest.raises(NotFoundError) as exc_info:
        await HassetteClient(session, f"{server_url}/api").get_health()

    assert exc_info.value.code == ProblemCode.NOT_FOUND


async def test_unknown_action_raises_the_servers_not_found(session: aiohttp.ClientSession, server_url: str) -> None:
    with pytest.raises(NotFoundError) as exc_info:
        await HassetteClient(session, server_url).action("my_app", "restart")  # pyright: ignore[reportArgumentType]

    assert exc_info.value.code in {ProblemCode.NOT_FOUND, ProblemCode.METHOD_NOT_ALLOWED}


async def test_base_url_pointing_at_the_web_ui_raises_unexpected_response(
    session: aiohttp.ClientSession, spa_server_url: str
) -> None:
    """A path outside ``/api`` reaches the SPA's HTML, which mustn't read as a schema mismatch."""
    with pytest.raises(UnexpectedResponseError) as exc_info:
        await HassetteClient(session, f"{spa_server_url}/ui").get_health()

    assert exc_info.value.content_type == "text/html"


async def test_action_round_trips(session: aiohttp.ClientSession, server_url: str) -> None:
    response = await HassetteClient(session, server_url).action("my_app", "start")

    assert response.app_key == "my_app"
    assert response.action == "start"
    assert response.instance_index is None


async def test_unknown_app_raises_app_not_found(session: aiohttp.ClientSession, server_url, mock_hassette) -> None:
    mock_hassette.telemetry_query_service.get_app_manifest.return_value = None

    with pytest.raises(AppNotFoundError) as exc_info:
        await HassetteClient(session, server_url).get_app("no_such_app")

    assert exc_info.value.code == ProblemCode.APP_NOT_FOUND


async def test_degraded_telemetry_raises_telemetry_unavailable(
    session: aiohttp.ClientSession, server_url: str, mock_hassette
) -> None:
    mock_hassette.telemetry_query_service.get_all_app_manifests = telemetry_error()

    with pytest.raises(TelemetryUnavailableError):
        await HassetteClient(session, server_url).get_apps()


async def test_telemetry_status_returns_its_model_when_degraded(
    session: aiohttp.ClientSession, server_url: str, mock_hassette
) -> None:
    mock_hassette.telemetry_query_service.check_health = telemetry_error()

    status = await HassetteClient(session, server_url).get_telemetry_status()

    assert status.degraded is True


async def test_token_is_accepted_by_an_auth_enabled_server(
    session: aiohttp.ClientSession, auth_server_url: str
) -> None:
    config = await HassetteClient(session, auth_server_url, token=WEB_API_TEST_TOKEN).get_config()

    assert config.config_schema


async def test_missing_token_raises_authentication_error(session: aiohttp.ClientSession, auth_server_url: str) -> None:
    with pytest.raises(AuthenticationError) as exc_info:
        await HassetteClient(session, auth_server_url).get_config()

    assert exc_info.value.code == ProblemCode.NOT_AUTHENTICATED
