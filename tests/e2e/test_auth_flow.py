"""E2E test: a cookie-authenticated session works end-to-end against a real running stack.

Injects a valid session cookie directly via ``context.add_cookies`` rather than driving the
login form UI — per design.md's Test Strategy ("New Test Coverage"): the login form itself is
covered by a dedicated frontend component test, and Playwright's limited ability to simulate a
server-initiated close mid-test means the WS-reconnect-on-rejected-handshake behavior is better
covered at the unit/component level too. This test's job is narrower and higher-altitude: prove
that a cookie which verifies correctly in isolation (``verify_session_cookie``, exercised in
``tests/integration/web_api/test_auth.py``) is actually sent by the browser and accepted by the
real serving origin for both a REST call and the WebSocket handshake — a ``SameSite``/``Secure``
mismatch or a middleware-ordering bug would pass every lower-level test and only show up here.

Requires the WebSocket-capable backend (``ws='websockets-sansio'``) — the shared ``live_server``
fixture starts uvicorn with ``ws='none'`` (see ``conftest.py``'s fixture-selection comment block)
and never serves the WS upgrade at all, so the WS half of this test could not pass against it.
This file builds its own auth-enabled fixtures rather than reusing ``live_server_ws`` because
that fixture's backing app has ``auth_enabled=False`` and no known token to mint a cookie
against.
"""

import asyncio
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from playwright.sync_api import Page, expect

from hassette.core.runtime_query_service import RuntimeQueryService
from hassette.testing.config import TEST_SESSION_TTL, WEB_API_TEST_TOKEN
from hassette.web.app import create_fastapi_app
from hassette.web.auth.session import SESSION_COOKIE_NAME, mint_session_cookie
from tests.e2e.conftest import build_mock_hassette
from tests.support.uvicorn import start_uvicorn_server, stop_uvicorn_server
from tests.support.web_mocks import create_mock_runtime_query_service

pytestmark = pytest.mark.e2e

WS_CONNECT_TIMEOUT_MS = 10000


@pytest.fixture
def mock_hassette_auth(ensure_spa_built: None) -> MagicMock:  # noqa: ARG001
    """A mock Hassette with auth enabled and a real ``session_ttl`` for cookie verification.

    ``create_hassette_stub()`` builds ``hassette.config.web_api`` as a ``MagicMock``, so
    ``session_ttl`` must be set explicitly here -- otherwise ``verify_session_cookie``'s TTL
    arithmetic would run against an auto-generated ``MagicMock`` attribute instead of an int.
    Kept separate from the module's shared ``mock_hassette`` (``auth_enabled=False`` there) so
    this test's auth-enabled server cannot bleed into the happy-path fixtures every other e2e
    test relies on.
    """
    hassette = build_mock_hassette(is_ready=True, auth_enabled=True)
    hassette.config.web_api.session_ttl = TEST_SESSION_TTL
    return hassette


@pytest.fixture
def runtime_query_service_auth(mock_hassette_auth: MagicMock) -> RuntimeQueryService:
    """Built with a mock lock -- swapped for a real ``asyncio.Lock`` in ``live_server_ws_auth``
    right before the server starts, mirroring ``conftest.py``'s ``live_server_ws`` fixture (see
    its docstring for why the swap happens that late rather than up front).
    """
    return create_mock_runtime_query_service(mock_hassette_auth, use_real_lock=False)


@pytest.fixture
def fastapi_app_auth(
    mock_hassette_auth: MagicMock,
    runtime_query_service_auth: RuntimeQueryService,  # noqa: ARG001
) -> FastAPI:
    """FastAPI app built with a known bearer token, so a cookie can be minted directly against it."""
    return create_fastapi_app(mock_hassette_auth, auth_token=WEB_API_TEST_TOKEN)


@pytest.fixture
def live_server_ws_auth(fastapi_app_auth: FastAPI, runtime_query_service_auth: RuntimeQueryService) -> Iterator[str]:
    """WebSocket-enabled uvicorn server (``ws='websockets-sansio'``) backed by an auth-enabled app.

    Function-scoped, mirroring ``conftest.py``'s ``live_server_ws`` -- the WS half of this test
    needs the real backend and its real ``websockets-sansio`` handshake, not the in-process ASGI
    transport the integration suite uses.
    """
    original_lock = runtime_query_service_auth._lock
    runtime_query_service_auth._lock = asyncio.Lock()

    server, thread, port = start_uvicorn_server(fastapi_app_auth, ws="websockets-sansio", timeout_graceful_shutdown=1)

    yield f"http://127.0.0.1:{port}"

    try:
        stop_uvicorn_server(server, thread)
    finally:
        runtime_query_service_auth._lock = original_lock


def test_cookie_authenticates_rest_and_websocket(page: Page, live_server_ws_auth: str) -> None:
    """A session cookie injected via ``context.add_cookies`` authenticates both the dashboard's
    initial REST load and the WebSocket handshake -- without driving the login form.
    """
    cookie_value = mint_session_cookie(WEB_API_TEST_TOKEN)
    page.context.add_cookies(
        [
            {
                "name": SESSION_COOKIE_NAME,
                "value": cookie_value,
                "url": live_server_ws_auth,
                "httpOnly": True,
                "secure": False,
                "sameSite": "Strict",
            }
        ]
    )

    page.goto(live_server_ws_auth + "/apps")

    # REST: the apps page renders from data fetched with the injected cookie
    # (frontend/src/api/client.ts sends `credentials: "same-origin"`). An unauthenticated request
    # would 401 and the frontend's QueryCache.onError redirects to /login instead
    # (frontend/src/lib/query-client.ts) -- reaching "apps-page" at all proves the cookie
    # authenticated the initial REST calls.
    expect(page.locator("[data-testid='apps-page']")).to_be_visible(timeout=WS_CONNECT_TIMEOUT_MS)
    expect(page.locator("[data-testid='login-page']")).not_to_be_visible()

    # WebSocket: the connection indicator reaches "Connected" only once the WS handshake
    # (authorize_ws() in web/auth.py, gated pre-accept() on the same cookie) succeeds and the
    # server sends its 'connected' message (web/routes/ws.py).
    ws_indicator = page.locator("[data-testid='ws-indicator']")
    expect(ws_indicator.first).to_have_text("Connected", timeout=WS_CONNECT_TIMEOUT_MS)
