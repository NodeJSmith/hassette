"""The SPA shell's per-request ``<base href>`` through the real app (design/specs/130-ingress-base-path)."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient

from hassette.testing.config import TEST_SESSION_TTL, WEB_API_TEST_TOKEN
from hassette.web.app import create_fastapi_app
from hassette.web.auth.trusted_proxies import TrustedProxySet
from hassette.web.spa import BASE_MARKER, FORWARDED_PREFIX_HEADER, INGRESS_PATH_HEADER
from tests.integration.web_api.conftest import HEALTH_PATH
from tests.support.web_mocks import (
    LOOPBACK,
    create_hassette_stub,
    create_mock_runtime_query_service,
    trusted_proxy_set,
)

INGRESS = "/api/hassio_ingress/tok_123"
INGRESS_BASE = f'<base href="{INGRESS}/" />'
LOOPBACK_TRUSTED = trusted_proxy_set(LOOPBACK)


def build_app(*, auth_enabled: bool, trusted: TrustedProxySet | None = None) -> FastAPI:
    hassette = create_hassette_stub(auth_enabled=auth_enabled)
    hassette.config.web_api.session_ttl = TEST_SESSION_TTL
    create_mock_runtime_query_service(hassette)
    return create_fastapi_app(hassette, auth_token=WEB_API_TEST_TOKEN, trusted_proxies=trusted)


@pytest.fixture
async def make_client(stub_spa: Path) -> AsyncIterator:  # noqa: ARG001
    clients: list[AsyncClient] = []

    def factory(*, auth_enabled: bool = True, trusted: TrustedProxySet | None = LOOPBACK_TRUSTED) -> AsyncClient:
        client = AsyncClient(
            transport=ASGITransport(app=build_app(auth_enabled=auth_enabled, trusted=trusted)),
            base_url="http://test",
        )
        clients.append(client)
        return client

    yield factory
    for client in clients:
        await client.aclose()


async def test_trusted_ingress_sets_base(make_client) -> None:
    resp = await make_client().get("/apps/foo", headers={INGRESS_PATH_HEADER: INGRESS})
    assert resp.status_code == 200
    assert INGRESS_BASE in resp.text


async def test_trusted_forwarded_prefix_sets_base(make_client) -> None:
    resp = await make_client().get("/", headers={FORWARDED_PREFIX_HEADER: "/hassette"})
    assert '<base href="/hassette/" />' in resp.text


async def test_trusted_peer_without_header_gets_root(make_client) -> None:
    resp = await make_client().get("/")
    assert resp.status_code == 200
    assert BASE_MARKER in resp.text


async def test_ingress_path_wins_over_forwarded_prefix(make_client) -> None:
    resp = await make_client().get("/", headers={INGRESS_PATH_HEADER: INGRESS, FORWARDED_PREFIX_HEADER: "/x"})
    assert INGRESS_BASE in resp.text


async def test_direct_index_html_is_substituted(make_client) -> None:
    resp = await make_client().get("/index.html", headers={INGRESS_PATH_HEADER: INGRESS})
    assert resp.status_code == 200
    assert INGRESS_BASE in resp.text
    assert resp.headers["cache-control"] == "no-cache"


async def test_shell_has_no_validators(make_client) -> None:
    resp = await make_client().get("/")
    assert "etag" not in resp.headers
    assert "last-modified" not in resp.headers
    assert resp.headers["vary"] == f"{INGRESS_PATH_HEADER}, {FORWARDED_PREFIX_HEADER}"


@pytest.mark.parametrize(
    ("client_kwargs", "headers", "remedy"),
    [
        pytest.param({"trusted": None}, {INGRESS_PATH_HEADER: INGRESS}, "web_api.trusted_proxies", id="untrusted"),
        pytest.param({}, {FORWARDED_PREFIX_HEADER: "//evil"}, "valid path prefix", id="malformed"),
        pytest.param(
            {"auth_enabled": False}, {INGRESS_PATH_HEADER: INGRESS}, "web_api.auth_enabled", id="trust-inactive"
        ),
    ],
)
async def test_rejected_header_gets_diagnostic_page(make_client, client_kwargs, headers, remedy) -> None:
    resp = await make_client(**client_kwargs).get("/apps/foo", headers=headers)
    assert resp.status_code == 403
    assert remedy in resp.text
    assert "<!-- stub -->" not in resp.text
    assert resp.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("path", ["/%00", "/foo%00bar"])
async def test_nul_in_path_serves_shell_not_500(make_client, path: str) -> None:
    resp = await make_client().get(path)
    assert resp.status_code == 200
    assert BASE_MARKER in resp.text


async def test_static_file_still_served_under_prefix(make_client) -> None:
    resp = await make_client().get("/assets/index-abc123.js", headers={INGRESS_PATH_HEADER: INGRESS})
    assert resp.status_code == 200


@pytest.mark.parametrize("breakage", ["no-marker", "no-index"])
async def test_broken_build_serves_no_ui_but_keeps_api(stub_spa: Path, breakage: str) -> None:
    index = stub_spa / "index.html"
    if breakage == "no-marker":
        index.write_text("<!-- stale build -->")
    else:
        index.unlink()
    app = build_app(auth_enabled=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/")).status_code == 404
        assert (await client.get("/assets/index-abc123.js")).status_code == 404
        assert (await client.get(HEALTH_PATH)).status_code != 404
