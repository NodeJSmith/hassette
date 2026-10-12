"""E2E test: the UI works end to end under a Home Assistant ingress prefix.

The browser talks only to an ingress-shaped aiohttp proxy (``tests/support/ingress_proxy.py``) that strips
``/api/hassio_ingress/<token>``, sets ``X-Ingress-Path``, and 404s anything outside the prefix. Hassette runs
with auth on and trusts the proxy's loopback address, as the add-on trusts Supervisor, so no login view
appears. Any frontend URL that escapes the prefix (an asset, font, REST call, WebSocket or navigation) fails
a request, which this test asserts never happens. The browser also sends a stray ``X-Forwarded-Prefix``, which
the proxy passes through as core does; ``X-Ingress-Path`` must still decide the base (D1). See
design/specs/130-ingress-base-path/design.md (D8).
"""

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from playwright.sync_api import Page, Request, Response, WebSocket, expect

from hassette.core.runtime_query_service import RuntimeQueryService
from hassette.testing.config import TEST_SESSION_TTL, WEB_API_TEST_TOKEN
from hassette.web.app import create_fastapi_app
from tests.e2e.conftest import build_mock_hassette, serve_ws
from tests.support.ingress_proxy import INGRESS_PATH, ingress_proxy
from tests.support.web_mocks import LOOPBACK, create_mock_runtime_query_service, trusted_proxy_set

pytestmark = pytest.mark.e2e

LOAD_TIMEOUT_MS = 10000
STRAY_PREFIX = "/evil"
"""A client-sent ``X-Forwarded-Prefix``; HA core forwards it, so the app must ignore it under ingress."""
FONT_LOADED_JS = (
    "document.fonts.ready.then(() => "
    "[...document.fonts].some(f => f.family.includes('Geist') && f.status === 'loaded'))"
)
"""Whether a self-hosted Geist face actually loaded (a 404'd font would be ``error``, not ``loaded``)."""


@pytest.fixture
def mock_hassette_ingress(ensure_spa_built: None) -> MagicMock:  # noqa: ARG001
    hassette = build_mock_hassette(is_ready=True, auth_enabled=True)
    hassette.config.web_api.session_ttl = TEST_SESSION_TTL
    return hassette


@pytest.fixture
def runtime_query_service_ingress(mock_hassette_ingress: MagicMock) -> RuntimeQueryService:
    return create_mock_runtime_query_service(mock_hassette_ingress, use_real_lock=False)


@pytest.fixture
def fastapi_app_ingress(
    mock_hassette_ingress: MagicMock,
    runtime_query_service_ingress: RuntimeQueryService,  # noqa: ARG001
) -> FastAPI:
    return create_fastapi_app(
        mock_hassette_ingress, auth_token=WEB_API_TEST_TOKEN, trusted_proxies=trusted_proxy_set(LOOPBACK)
    )


@pytest.fixture
def ingress_url(fastapi_app_ingress: FastAPI, runtime_query_service_ingress: RuntimeQueryService) -> Iterator[str]:
    """The app behind the ingress proxy; yields the proxy's ``.../api/hassio_ingress/<token>/`` URL."""
    with serve_ws(fastapi_app_ingress, runtime_query_service_ingress) as upstream, ingress_proxy(upstream) as url:
        yield url


def test_ui_works_under_ingress_prefix(page: Page, ingress_url: str) -> None:
    escaped: list[str] = []
    failed: list[str] = []
    websockets: list[str] = []

    def on_request(request: Request) -> None:
        if INGRESS_PATH not in request.url:
            escaped.append(request.url)

    def on_response(response: Response) -> None:
        if response.status >= 400:
            failed.append(f"{response.status} {response.url}")

    def on_request_failed(request: Request) -> None:
        # In-flight fetches the reload below cancels are aborted, not misrouted.
        if request.failure != "net::ERR_ABORTED":
            failed.append(f"{request.failure} {request.url}")

    def on_websocket(ws: WebSocket) -> None:
        # page.on("request") never sees WebSocket handshakes.
        websockets.append(ws.url)

    page.set_extra_http_headers({"X-Forwarded-Prefix": STRAY_PREFIX})
    page.on("request", on_request)
    page.on("websocket", on_websocket)
    page.on("response", on_response)
    page.on("requestfailed", on_request_failed)

    # Loads with no login view: the proxy is a trusted peer, so hassette auth is bypassed.
    page.goto(ingress_url)
    expect(page.locator("[data-testid='apps-page']")).to_be_visible(timeout=LOAD_TIMEOUT_MS)
    expect(page.locator("[data-testid='login-page']")).not_to_be_visible()
    expect(page).to_have_url(f"{ingress_url}apps")

    # The live WebSocket connects through the proxy.
    expect(page.locator("[data-testid='ws-indicator']").first).to_have_text("Connected", timeout=LOAD_TIMEOUT_MS)

    # Styles and self-hosted fonts load from under the prefix.
    assert page.evaluate(FONT_LOADED_JS)
    assert "Geist" in page.evaluate("getComputedStyle(document.body).fontFamily")

    # Client-side navigation stays under the prefix.
    page.locator("[data-testid='nav-logs']").first.click()
    expect(page.locator("[data-testid='logs-page']")).to_be_visible(timeout=LOAD_TIMEOUT_MS)
    expect(page).to_have_url(f"{ingress_url}logs")

    # A deep-link reload resolves its assets against the injected <base href>.
    page.reload()
    expect(page.locator("[data-testid='logs-page']")).to_be_visible(timeout=LOAD_TIMEOUT_MS)
    assert page.evaluate(FONT_LOADED_JS)

    assert escaped == []
    assert failed == []
    assert websockets
    assert all(INGRESS_PATH in url and STRAY_PREFIX not in url for url in websockets)
