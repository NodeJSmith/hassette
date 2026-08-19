"""Integration tests for the default-deny auth middleware.

Covers the generic deny/exempt/bypass behavior across the endpoint categories the design names
(mutation endpoints, source-disclosure endpoints, config), the `/api/` prefix scope, sliding
session-cookie renewal, coalesced failed-auth counting, and the `POST /api/auth/session` login
exchange itself, reachable with zero prior credential -- plus the full assembled bearer token,
session cookie, trusted-proxy (peer and hostname), spoofed-header rejection, session TTL, and
CORS-preflight coverage.

The failed-auth counting test against the login path drives the real `POST /api/auth/session`
handler with a wrong token to prove the counting *mechanism* (any outgoing 401 from an exempt
route is counted, not just the middleware's own reject branch) -- the login handler is exempt from
`DefaultDenyMiddleware`'s default-deny but still issues its own 401 for an invalid token.
"""

import logging
import time
from pathlib import Path
from typing import Literal
from unittest.mock import AsyncMock, patch

import pytest
from httpx2 import ASGITransport, AsyncClient, Response

import hassette.web.app as web_app
from hassette.test_utils import make_addrinfo, patch_loop_getaddrinfo
from hassette.test_utils.config import TEST_SESSION_TTL, WEB_API_TEST_TOKEN
from hassette.test_utils.web_mocks import create_hassette_stub, create_mock_runtime_query_service
from hassette.web.app import create_fastapi_app
from hassette.web.auth.session import SESSION_COOKIE_NAME, mint_session_cookie, verify_session_cookie
from hassette.web.auth.trusted_proxies import refresh_trusted_proxies, resolve_trusted_proxies
from hassette.web.middleware import FAILED_AUTH_THRESHOLD

from .conftest import make_log_record

_STUB_SPA_FILES = ("index.html", "assets/index-abc123.js")
_TRUSTED_PEER_IP = "203.0.113.5"
"""Peer address the trusted-proxy tests list in `trusted_proxies` (RFC 5737 doc range)."""

_UNTRUSTED_PEER_IP = "198.51.100.9"
"""Peer address deliberately outside every test's `trusted_proxies` set."""


@pytest.fixture(autouse=True)
def _propagate_hassette_logger() -> None:
    """Ensure the "hassette" logger propagates so caplog can see records.

    Some other test in the session may have left `propagate` set to False (e.g. via
    `enable_basic_logging()`) -- caplog relies on propagation to the root logger. Same
    workaround as `tests/unit/web/test_auth.py`.
    """
    logging.getLogger("hassette").propagate = True


@pytest.fixture
def stub_spa(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create minimal stub SPA files in a private tmp directory and point `_SPA_DIR` at it.

    `create_fastapi_app()` only mounts `/assets` and registers the SPA catch-all when
    `_SPA_DIR.exists()` is True at call time -- this dev checkout has no built frontend, so
    without this fixture `GET /` and `GET /assets/*` would 404 (no route at all) rather than
    exercising the actual SPA-serving code path.

    Uses `tmp_path` (unique per test, and therefore per pytest-xdist worker) and monkeypatches
    `hassette.web.app._SPA_DIR` rather than writing to the real, shared `src/hassette/web/
    static/spa/` directory `web/app.py` normally reads -- writing to that shared path raced
    against `tests/integration/test_packaging.py`'s own `stub_spa` fixture under parallel test
    runs (#1629). `_SPA_DIR` is read fresh from the module on every `create_fastapi_app()` call,
    so patching it here is sufficient without touching production code.
    """
    spa_dir = tmp_path / "spa"
    (spa_dir / "assets").mkdir(parents=True)
    for relative in _STUB_SPA_FILES:
        f = spa_dir / relative
        f.write_text("<!-- stub -->" if relative.endswith(".html") else "/* stub */")

    monkeypatch.setattr(web_app, "_SPA_DIR", spa_dir)
    return spa_dir


async def _mint_cookie_at(token: str, seconds_ago: int) -> str:
    """Mint a session cookie as if it were minted `seconds_ago` seconds in the past."""
    stale_timestamp = int(time.time()) - seconds_ago
    with patch("hassette.web.auth.session._current_timestamp", return_value=stale_timestamp):
        return mint_session_cookie(token)


async def _request_from_peer(
    auth_hassette,
    peer: str,
    *,
    trusted_proxies,
    method: Literal["get", "post"] = "get",
    path: str = "/api/config",
    headers: dict[str, str] | None = None,
    json: dict | None = None,
    **app_kwargs,
) -> Response:
    """Issue one request from `peer` against a fresh app built with `trusted_proxies`.

    Builds `create_fastapi_app(auth_hassette, trusted_proxies=trusted_proxies, **app_kwargs)`,
    wraps it in an `ASGITransport` whose ASGI `client` is `(peer, 12345)`, opens an `AsyncClient`
    against it, and issues one `method` request to `path`. Extracted because this exact
    build-app/wrap-transport/open-client/issue-request sequence repeated near-verbatim across the
    trusted-proxy, sliding-renewal, and cookie-secure-flag tests, differing only in the peer IP,
    the `trusted_proxies`/`auth_token` app kwargs, and the request itself.

    `trusted_proxies` takes an already-resolved set (not raw hostnames/IPs) -- resolution differs
    enough across callers (plain IP/CIDR, mocked-DNS hostname, post-refresh) that it stays in each
    test body rather than being folded into this helper.
    """
    app = create_fastapi_app(auth_hassette, trusted_proxies=trusted_proxies, **app_kwargs)
    transport = ASGITransport(app=app, client=(peer, 12345))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        request_kwargs: dict = {}
        if headers is not None:
            request_kwargs["headers"] = headers
        if json is not None:
            request_kwargs["json"] = json
        return await getattr(client, method)(path, **request_kwargs)


async def _trusted_peer_get_config(auth_hassette, headers: dict[str, str] | None = None) -> Response:
    """`GET /api/config` from a peer inside `trusted_proxies`, against an app with a real token.

    Both halves matter: the peer matches, *and* `auth_token` is configured -- so a request that
    presents a credential has something real to be validated against, rather than the
    no-token apps `TestTrustedProxyPeerAuth` builds.
    """
    trusted = await resolve_trusted_proxies((_TRUSTED_PEER_IP,))
    return await _request_from_peer(
        auth_hassette, _TRUSTED_PEER_IP, trusted_proxies=trusted, headers=headers, auth_token=WEB_API_TEST_TOKEN
    )


class TestDefaultDenyNoCredential:
    """Every non-exempt `/api/*` route rejects a request with no credential."""

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("post", "/api/apps/my_app/start"),  # mutation endpoint
            ("get", "/api/apps/my_app/source"),  # source-disclosure endpoint
            ("get", "/api/config"),  # source-disclosure endpoint
            ("get", "/api/apps"),  # representative non-exempt route
            ("get", "/api/docs"),  # deliberately no longer exempt (design.md Edge Cases)
            ("get", "/api/openapi.json"),  # deliberately no longer exempt
        ],
    )
    async def test_no_credential_returns_401(self, auth_client: AsyncClient, method: str, path: str) -> None:
        resp = await getattr(auth_client, method)(path)
        assert resp.status_code == 401


class TestExemptRoutes:
    """The three exemptions bypass the trusted-peer/bearer/cookie checks entirely."""

    async def test_health_live_reachable_with_no_credential(self, auth_client: AsyncClient) -> None:
        resp = await auth_client.get("/api/health/live")
        assert resp.status_code != 401

    async def test_health_ready_reachable_with_no_credential(self, auth_client: AsyncClient) -> None:
        resp = await auth_client.get("/api/health/ready")
        assert resp.status_code != 401

    async def test_auth_session_reachable_with_no_credential(self, auth_client: AsyncClient) -> None:
        # A correct-token request with zero prior credential succeeds -- proving the route is
        # reachable *and* functional, not just "not rejected by the middleware".
        resp = await auth_client.post("/api/auth/session", json={"token": WEB_API_TEST_TOKEN})
        assert resp.status_code == 200
        assert SESSION_COOKIE_NAME in resp.cookies


class TestAuthSessionRoute:
    """`POST /api/auth/session` validates the presented token and mints a session cookie."""

    async def test_correct_token_mints_verifiable_cookie(self, auth_client: AsyncClient) -> None:
        resp = await auth_client.post("/api/auth/session", json={"token": WEB_API_TEST_TOKEN})

        assert resp.status_code == 200
        cookie_value = resp.cookies.get(SESSION_COOKIE_NAME)
        assert cookie_value is not None
        assert verify_session_cookie(cookie_value, WEB_API_TEST_TOKEN, TEST_SESSION_TTL) is not None

    async def test_incorrect_token_returns_401(self, auth_client: AsyncClient) -> None:
        resp = await auth_client.post("/api/auth/session", json={"token": "wrong-token"})

        assert resp.status_code == 401
        assert SESSION_COOKIE_NAME not in resp.cookies

    async def test_minted_cookie_authenticates_subsequent_request(self, auth_client: AsyncClient) -> None:
        login_resp = await auth_client.post("/api/auth/session", json={"token": WEB_API_TEST_TOKEN})
        assert login_resp.status_code == 200

        resp = await auth_client.get("/api/config")
        assert resp.status_code == 200


class TestAuthDisabledBypass:
    """`auth_enabled=False` is a full, side-effect-free bypass of the middleware.

    This is the specific behavior that keeps `create_hassette_stub()`'s default
    (`auth_enabled=False`) -- used by the existing integration test suite -- passing unchanged.
    """

    async def test_mutation_endpoint_returns_non_401_when_auth_disabled(self, client: AsyncClient) -> None:
        # `client` (conftest.py) wraps `create_hassette_stub()`'s default auth_enabled=False.
        resp = await client.post("/api/apps/my_app/start")
        assert resp.status_code != 401


class TestMiddlewareScope:
    """The middleware gates the `/api/` prefix only -- the SPA bundle stays reachable."""

    @pytest.mark.usefixtures("stub_spa")
    async def test_root_reachable_with_no_credential(self, auth_client: AsyncClient) -> None:
        resp = await auth_client.get("/")
        assert resp.status_code == 200
        assert "<!-- stub -->" in resp.text

    @pytest.mark.usefixtures("stub_spa")
    async def test_assets_path_reachable_with_no_credential(self, auth_client: AsyncClient) -> None:
        resp = await auth_client.get("/assets/index-abc123.js")
        assert resp.status_code == 200

    async def test_config_still_requires_credential(self, auth_client: AsyncClient) -> None:
        resp = await auth_client.get("/api/config")
        assert resp.status_code == 401

    async def test_cors_preflight_gets_cors_response_not_opaque_401(self, auth_client: AsyncClient) -> None:
        """Verifies the middleware-registration-ordering claim (design.md Open Questions).

        A preflight OPTIONS request against a protected route with no credential must get a real
        CORS response (CORSMiddleware handles it directly, never delegating to the inner app for a
        genuine preflight), not an opaque 401 with no CORS headers -- which is what would happen if
        DefaultDenyMiddleware were the outer layer instead of CORSMiddleware.
        """
        resp = await auth_client.options(
            "/api/config",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code != 401
        header_names = {name.lower() for name in resp.headers}
        assert "access-control-allow-origin" in header_names


class TestSlidingRenewal:
    """A cookie past its half-life is renewed; a fresh one, or a non-cookie credential, is not."""

    async def test_stale_cookie_gets_renewed(self, auth_client: AsyncClient) -> None:
        # Past half of TEST_SESSION_TTL (1800s) but still under the full TTL (3600s).
        stale_cookie = await _mint_cookie_at(WEB_API_TEST_TOKEN, seconds_ago=2000)
        auth_client.cookies.set(SESSION_COOKIE_NAME, stale_cookie)

        resp = await auth_client.get("/api/config")

        assert resp.status_code == 200
        new_value = resp.cookies.get(SESSION_COOKIE_NAME)
        assert new_value is not None
        assert new_value != stale_cookie
        assert verify_session_cookie(new_value, WEB_API_TEST_TOKEN, TEST_SESSION_TTL) is not None

    async def test_fresh_cookie_is_not_renewed(self, auth_client: AsyncClient) -> None:
        fresh_cookie = await _mint_cookie_at(WEB_API_TEST_TOKEN, seconds_ago=10)
        auth_client.cookies.set(SESSION_COOKIE_NAME, fresh_cookie)

        resp = await auth_client.get("/api/config")

        assert resp.status_code == 200
        assert resp.cookies.get(SESSION_COOKIE_NAME) is None

    async def test_bearer_authenticated_request_is_not_renewed(self, auth_client: AsyncClient) -> None:
        resp = await auth_client.get("/api/config", headers={"Authorization": f"Bearer {WEB_API_TEST_TOKEN}"})

        assert resp.status_code == 200
        assert resp.cookies.get(SESSION_COOKIE_NAME) is None

    async def test_trusted_proxy_authenticated_request_is_not_renewed(self, auth_hassette) -> None:
        trusted = await resolve_trusted_proxies((_TRUSTED_PEER_IP,))
        resp = await _request_from_peer(
            auth_hassette, _TRUSTED_PEER_IP, trusted_proxies=trusted, auth_token=WEB_API_TEST_TOKEN
        )

        assert resp.status_code == 200
        assert resp.cookies.get(SESSION_COOKIE_NAME) is None


class TestFailedAuthCounting:
    """A burst of failed-auth (401) responses from one source produces exactly one coalesced
    WARN, not one per attempt.
    """

    async def test_burst_against_gated_route_produces_one_coalesced_warn(
        self, auth_client: AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="hassette.web.middleware"):
            for _ in range(FAILED_AUTH_THRESHOLD):
                resp = await auth_client.get("/api/config", headers={"Authorization": "Bearer wrong-token"})
                assert resp.status_code == 401

        warn_records = [r for r in caplog.records if "failed auth attempts" in r.getMessage()]
        assert len(warn_records) == 1

    async def test_burst_against_login_route_produces_one_coalesced_warn(
        self, auth_hassette, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The counter keys off the outgoing 401, not off this middleware's own reject branch --
        an exempt route's own handler-issued 401 must be counted by the same rule.

        `POST /api/auth/session` is exempt from `DefaultDenyMiddleware`'s default-deny (it must be
        reachable with zero prior credential), so this drives the real handler with a wrong token --
        it rejects with its own 401 rather than the middleware's -- to prove the counting mechanism
        applies there too.
        """
        app = create_fastapi_app(auth_hassette, auth_token=WEB_API_TEST_TOKEN)

        transport = ASGITransport(app=app)
        with caplog.at_level(logging.WARNING, logger="hassette.web.middleware"):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                for _ in range(FAILED_AUTH_THRESHOLD):
                    resp = await client.post("/api/auth/session", json={"token": "wrong"})
                    assert resp.status_code == 401

        warn_records = [r for r in caplog.records if "failed auth attempts" in r.getMessage()]
        assert len(warn_records) == 1


class TestMutationSuccessLogging:
    """A successful authenticated mutation action logs an INFO line naming the action and source
    IP, via the existing "hassette" logger, retrievable via `GET /api/logs/recent`.
    """

    @pytest.fixture
    def mutation_hassette(self):
        """`auth_enabled=True` plus `app_action_mocks=True` so start/stop/reload succeed."""
        hassette = create_hassette_stub(auth_enabled=True, app_action_mocks=True)
        hassette.config.web_api.session_ttl = TEST_SESSION_TTL
        create_mock_runtime_query_service(hassette)
        return hassette

    async def test_start_app_logs_action_and_source_ip(
        self, mutation_hassette, caplog: pytest.LogCaptureFixture
    ) -> None:
        app = create_fastapi_app(mutation_hassette, auth_token=WEB_API_TEST_TOKEN)
        transport = ASGITransport(app=app, client=("203.0.113.7", 54321))

        with caplog.at_level(logging.INFO, logger="hassette.web.routes.apps"):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/apps/my_app/start", headers={"Authorization": f"Bearer {WEB_API_TEST_TOKEN}"}
                )
                assert resp.status_code == 202

                info_records = [r for r in caplog.records if "Started app" in r.getMessage()]
                assert len(info_records) == 1
                message = info_records[0].getMessage()
                assert "my_app" in message
                assert "203.0.113.7" in message

                # The same record surfaces via GET /api/logs/recent once the real LoggingService
                # persistence pipeline has written it -- proves this is the kind of record the
                # dashboard's log view can show, not just a bare logger call.
                mutation_hassette.telemetry_query_service.get_log_records = AsyncMock(
                    return_value=[make_log_record(1, message=message)]
                )
                logs_resp = await client.get(
                    "/api/logs/recent", headers={"Authorization": f"Bearer {WEB_API_TEST_TOKEN}"}
                )
                assert logs_resp.status_code == 200
                messages = [r["message"] for r in logs_resp.json()]
                assert any("Started app my_app" in m and "203.0.113.7" in m for m in messages)

    async def test_log_level_change_logs_action_and_source_ip(
        self, mutation_hassette, caplog: pytest.LogCaptureFixture
    ) -> None:
        app = create_fastapi_app(mutation_hassette, auth_token=WEB_API_TEST_TOKEN)
        transport = ASGITransport(app=app, client=(_UNTRUSTED_PEER_IP, 54321))

        with caplog.at_level(logging.INFO, logger="hassette.web.routes.logs"):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.put(
                    "/api/logs/level",
                    json={"logger": "hassette.test_logger", "level": "DEBUG"},
                    headers={"Authorization": f"Bearer {WEB_API_TEST_TOKEN}"},
                )
                assert resp.status_code == 200

        info_records = [r for r in caplog.records if "Changed log level" in r.getMessage()]
        assert len(info_records) == 1
        message = info_records[0].getMessage()
        assert "hassette.test_logger" in message
        assert _UNTRUSTED_PEER_IP in message


class TestBearerTokenAuth:
    """A bearer token directly authenticates a general gated route.

    Distinct from `TestAuthSessionRoute`, which drives the same token through the login
    exchange -- this exercises the middleware's own `Authorization` header check against an
    arbitrary `/api/*` route, not the login handler's body-based validation.
    """

    async def test_wrong_bearer_token_returns_401(self, auth_client: AsyncClient) -> None:
        resp = await auth_client.get("/api/config", headers={"Authorization": "Bearer wrong-token"})
        assert resp.status_code == 401

    async def test_correct_bearer_token_returns_200(self, auth_client: AsyncClient) -> None:
        resp = await auth_client.get("/api/config", headers={"Authorization": f"Bearer {WEB_API_TEST_TOKEN}"})
        assert resp.status_code == 200


class TestSessionCookieAuth:
    """A correct session cookie, minted directly (not via the login route), authenticates a
    gated route.
    """

    async def test_correct_cookie_returns_200(self, auth_client: AsyncClient) -> None:
        cookie_value = mint_session_cookie(WEB_API_TEST_TOKEN)
        auth_client.cookies.set(SESSION_COOKIE_NAME, cookie_value)

        resp = await auth_client.get("/api/config")

        assert resp.status_code == 200


class TestTrustedProxyPeerAuth:
    """A request whose ASGI peer matches a `trusted_proxies` IP or CIDR entry is authenticated
    with no credential at all. No `auth_token` is configured on these apps -- the whole point
    is that the trusted-peer path never needs one.
    """

    async def test_ip_entry_peer_returns_200_with_no_credential(self, auth_hassette) -> None:
        trusted = await resolve_trusted_proxies((_TRUSTED_PEER_IP,))
        resp = await _request_from_peer(auth_hassette, _TRUSTED_PEER_IP, trusted_proxies=trusted)

        assert resp.status_code == 200

    async def test_cidr_entry_peer_returns_200_with_no_credential(self, auth_hassette) -> None:
        trusted = await resolve_trusted_proxies(("10.0.0.0/24",))
        resp = await _request_from_peer(auth_hassette, "10.0.0.42", trusted_proxies=trusted)

        assert resp.status_code == 200

    async def test_non_matching_peer_still_requires_credential(self, auth_hassette) -> None:
        trusted = await resolve_trusted_proxies((_TRUSTED_PEER_IP,))
        resp = await _request_from_peer(auth_hassette, _UNTRUSTED_PEER_IP, trusted_proxies=trusted)

        assert resp.status_code == 401


class TestPresentedCredentialPrecedence:
    """A presented `Authorization` header is authoritative: it is always validated, and every
    invalid form of it fails closed with a 401 -- even when the peer matches `trusted_proxies`.
    Ambient peer trust applies only to a request presenting no `Authorization` header at all.

    Without this ordering, `trusted_proxies` and bearer-token API access are mutually exclusive on
    one host: a reverse-proxy bypass router that routes on the *presence* of an `Authorization`
    header (Traefik `HeaderRegexp(Authorization, .+)`) becomes a full auth bypass, since the peer
    match short-circuits before the token is ever compared.
    """

    async def test_correct_bearer_token_from_trusted_peer_returns_200(self, auth_hassette) -> None:
        resp = await _trusted_peer_get_config(auth_hassette, headers={"Authorization": f"Bearer {WEB_API_TEST_TOKEN}"})

        assert resp.status_code == 200

    async def test_wrong_bearer_token_from_trusted_peer_returns_401(self, auth_hassette) -> None:
        resp = await _trusted_peer_get_config(auth_hassette, headers={"Authorization": "Bearer wrong-token"})

        assert resp.status_code == 401

    async def test_unrecognized_scheme_from_trusted_peer_returns_401(self, auth_hassette) -> None:
        """A malformed header fails closed too, not just a wrong token: a surprising 401 to a
        misconfigured client beats a bypass a trusted peer could exploit.
        """
        resp = await _trusted_peer_get_config(auth_hassette, headers={"Authorization": f"Basic {WEB_API_TEST_TOKEN}"})

        assert resp.status_code == 401

    async def test_empty_bearer_value_from_trusted_peer_returns_401(self, auth_hassette) -> None:
        resp = await _trusted_peer_get_config(auth_hassette, headers={"Authorization": "Bearer "})

        assert resp.status_code == 401

    async def test_no_authorization_header_from_trusted_peer_returns_200(self, auth_hassette) -> None:
        """The existing no-credential peer-trust path is untouched -- this is what keeps a browser
        behind a forward-auth proxy from having to pass Hassette's own login screen as well.
        """
        resp = await _trusted_peer_get_config(auth_hassette)

        assert resp.status_code == 200

    async def test_wrong_bearer_token_does_not_fall_back_to_valid_cookie(self, auth_client: AsyncClient) -> None:
        """A presented header is authoritative over a valid session cookie too, not only over peer
        trust. Browsers never send `Authorization` unprompted, so this combination only arises from
        a deliberate client -- and a deliberate client sending a bad token should be told, not
        silently authenticated by a leftover cookie.
        """
        auth_client.cookies.set(SESSION_COOKIE_NAME, mint_session_cookie(WEB_API_TEST_TOKEN))

        resp = await auth_client.get("/api/config", headers={"Authorization": "Bearer wrong-token"})

        assert resp.status_code == 401


class TestTrustedProxyHostnameAuth:
    """A request whose peer matches a `trusted_proxies` hostname entry is authenticated with no
    credential; the trusted set updates after a simulated periodic-refresh tick.
    """

    async def test_hostname_entry_peer_returns_200_with_no_credential(self, auth_hassette) -> None:
        with patch_loop_getaddrinfo(return_value=[make_addrinfo("172.30.32.2")]):
            trusted = await resolve_trusted_proxies(("proxy.internal",))

        resp = await _request_from_peer(auth_hassette, "172.30.32.2", trusted_proxies=trusted)

        assert resp.status_code == 200

    async def test_refresh_tick_trusts_new_resolved_address(self, auth_hassette) -> None:
        with patch_loop_getaddrinfo(return_value=[make_addrinfo("172.30.32.2")]):
            trusted = await resolve_trusted_proxies(("proxy.internal",))

        # Simulated periodic-refresh tick: the sibling proxy container was recreated with a new
        # IP (same hostname), exactly as `Scheduler.run_every()` would observe on its next run.
        with patch_loop_getaddrinfo(return_value=[make_addrinfo("172.30.32.9")]):
            refreshed = await refresh_trusted_proxies(trusted)

        new_resp = await _request_from_peer(auth_hassette, "172.30.32.9", trusted_proxies=refreshed)
        assert new_resp.status_code == 200

        # The pre-refresh address is no longer part of the current resolution.
        old_resp = await _request_from_peer(auth_hassette, "172.30.32.2", trusted_proxies=refreshed)
        assert old_resp.status_code == 401


class TestSpoofedForwardedForRejected:
    """A spoofed `X-Forwarded-For` header from an untrusted direct peer is rejected exactly like
    any other unauthenticated request -- the test that most directly proves the peer-only trust
    guarantee holds end-to-end through the real app, not just in the matcher function's isolated
    signature.
    """

    async def test_spoofed_x_forwarded_for_from_untrusted_peer_returns_401(self, auth_hassette) -> None:
        trusted = await resolve_trusted_proxies((_TRUSTED_PEER_IP,))
        # The direct ASGI peer is untrusted -- only the client-suppliable header claims the
        # trusted IP, which `is_trusted_peer` must never consult.
        resp = await _request_from_peer(
            auth_hassette, _UNTRUSTED_PEER_IP, trusted_proxies=trusted, headers={"X-Forwarded-For": _TRUSTED_PEER_IP}
        )

        assert resp.status_code == 401


class TestSessionCookieTtlIntegration:
    """A cookie minted more than `session_ttl` seconds ago is rejected on the next request; one
    minted within the TTL is accepted.
    """

    async def test_cookie_past_full_ttl_returns_401(self, auth_client: AsyncClient) -> None:
        expired_cookie = await _mint_cookie_at(WEB_API_TEST_TOKEN, seconds_ago=TEST_SESSION_TTL + 100)
        auth_client.cookies.set(SESSION_COOKIE_NAME, expired_cookie)

        resp = await auth_client.get("/api/config")

        assert resp.status_code == 401

    async def test_cookie_within_ttl_returns_200(self, auth_client: AsyncClient) -> None:
        fresh_cookie = await _mint_cookie_at(WEB_API_TEST_TOKEN, seconds_ago=100)
        auth_client.cookies.set(SESSION_COOKIE_NAME, fresh_cookie)

        resp = await auth_client.get("/api/config")

        assert resp.status_code == 200


class TestCookieSecureFlag:
    """A trusted peer with `X-Forwarded-Proto: https` gets a `Secure`-flagged cookie from
    `POST /api/auth/session`; a non-trusted peer with the same spoofed header does not.
    """

    async def test_trusted_peer_with_https_forwarded_proto_gets_secure_cookie(self, auth_hassette) -> None:
        trusted = await resolve_trusted_proxies((_TRUSTED_PEER_IP,))
        resp = await _request_from_peer(
            auth_hassette,
            _TRUSTED_PEER_IP,
            trusted_proxies=trusted,
            auth_token=WEB_API_TEST_TOKEN,
            method="post",
            path="/api/auth/session",
            json={"token": WEB_API_TEST_TOKEN},
            headers={"X-Forwarded-Proto": "https"},
        )

        assert resp.status_code == 200
        set_cookie_header = resp.headers.get("set-cookie")
        assert set_cookie_header is not None
        assert "secure" in set_cookie_header.lower()

    async def test_non_trusted_peer_with_spoofed_https_header_gets_no_secure_cookie(self, auth_hassette) -> None:
        trusted = await resolve_trusted_proxies((_TRUSTED_PEER_IP,))
        # Direct peer does not match trusted_proxies -- the header is spoofed and must be ignored
        # per `should_set_secure_cookie_flag`'s contract.
        resp = await _request_from_peer(
            auth_hassette,
            _UNTRUSTED_PEER_IP,
            trusted_proxies=trusted,
            auth_token=WEB_API_TEST_TOKEN,
            method="post",
            path="/api/auth/session",
            json={"token": WEB_API_TEST_TOKEN},
            headers={"X-Forwarded-Proto": "https"},
        )

        assert resp.status_code == 200
        set_cookie_header = resp.headers.get("set-cookie")
        assert set_cookie_header is not None
        assert "secure" not in set_cookie_header.lower()
