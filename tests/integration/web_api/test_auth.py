"""Integration tests for the default-deny auth middleware.

Covers the generic deny/exempt/bypass behavior across the endpoint categories the design names
(mutation endpoints, source-disclosure endpoints, config), the `/api/` prefix scope, sliding
session-cookie renewal, coalesced failed-auth counting, and the `POST /api/auth/session` login
exchange itself, reachable with zero prior credential.

The failed-auth counting test against the login path drives the real `POST /api/auth/session`
handler with a wrong token to prove the counting *mechanism* (any outgoing 401 from an exempt
route is counted, not just the middleware's own reject branch) -- the login handler is exempt from
`DefaultDenyMiddleware`'s default-deny but still issues its own 401 for an invalid token.

A later test suite extends this file with the full assembled bearer/cookie/trusted-proxy/CORS
coverage -- this file covers only the generic deny/exempt/bypass/scope/renewal/counting behavior.
"""

import contextlib
import logging
import time
from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx2 import ASGITransport, AsyncClient

from hassette.test_utils.web_mocks import create_hassette_stub, create_mock_runtime_query_service
from hassette.web.app import create_fastapi_app
from hassette.web.auth import SESSION_COOKIE_NAME, mint_session_cookie, resolve_trusted_proxies, verify_session_cookie
from hassette.web.middleware import FAILED_AUTH_THRESHOLD

from .conftest import make_log_record

TEST_TOKEN = "test-token-value"
SESSION_TTL = 3600

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SPA_DIR = _PROJECT_ROOT / "src" / "hassette" / "web" / "static" / "spa"
_STUB_SPA_FILES = ("index.html", "assets/index-abc123.js")


@pytest.fixture(autouse=True)
def _propagate_hassette_logger() -> None:
    """Ensure the "hassette" logger propagates so caplog can see records.

    Some other test in the session may have left `propagate` set to False (e.g. via
    `enable_basic_logging()`) -- caplog relies on propagation to the root logger. Same
    workaround as `tests/unit/web/test_auth.py`.
    """
    logging.getLogger("hassette").propagate = True


@pytest.fixture
def stub_spa() -> Generator[Path, None, None]:
    """Create minimal stub SPA files at the real, on-disk `_SPA_DIR` path `web/app.py` reads.

    `create_fastapi_app()` only mounts `/assets` and registers the SPA catch-all when
    `_SPA_DIR.exists()` is True at call time -- this dev checkout has no built frontend, so
    without this fixture `GET /` and `GET /assets/*` would 404 (no route at all) rather than
    exercising the actual SPA-serving code path. Mirrors `tests/integration/test_packaging.py`'s
    `stub_spa` fixture.
    """
    _SPA_DIR.mkdir(parents=True, exist_ok=True)
    assets_dir = _SPA_DIR / "assets"
    assets_dir.mkdir(exist_ok=True)

    created: list[Path] = []
    try:
        for relative in _STUB_SPA_FILES:
            f = _SPA_DIR / relative
            f.write_text("<!-- stub -->" if relative.endswith(".html") else "/* stub */")
            created.append(f)
        yield _SPA_DIR
    finally:
        for f in created:
            f.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            assets_dir.rmdir()
        with contextlib.suppress(OSError):
            _SPA_DIR.rmdir()


@pytest.fixture
def auth_hassette():
    """A `create_hassette_stub()` with `auth_enabled=True` and a real `session_ttl`.

    `create_hassette_stub()` doesn't set `session_ttl` on the MagicMock stub -- this fixture sets
    it directly so `verify_session_cookie`/`should_renew_session_cookie` (which do arithmetic
    against it) don't operate on an auto-generated `MagicMock` attribute.
    """
    hassette = create_hassette_stub(auth_enabled=True)
    hassette.config.web_api.session_ttl = SESSION_TTL
    create_mock_runtime_query_service(hassette)
    return hassette


@pytest.fixture
def auth_app(auth_hassette):
    """FastAPI app built with a known token, so bearer/cookie assertions have a concrete value."""
    return create_fastapi_app(auth_hassette, auth_token=TEST_TOKEN)


@pytest.fixture
async def auth_client(auth_app):
    transport = ASGITransport(app=auth_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


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
        resp = await auth_client.post("/api/auth/session", json={"token": TEST_TOKEN})
        assert resp.status_code == 200
        assert SESSION_COOKIE_NAME in resp.cookies


class TestAuthSessionRoute:
    """`POST /api/auth/session` validates the presented token and mints a session cookie."""

    async def test_correct_token_mints_verifiable_cookie(self, auth_client: AsyncClient) -> None:
        resp = await auth_client.post("/api/auth/session", json={"token": TEST_TOKEN})

        assert resp.status_code == 200
        cookie_value = resp.cookies.get(SESSION_COOKIE_NAME)
        assert cookie_value is not None
        assert verify_session_cookie(cookie_value, TEST_TOKEN, SESSION_TTL) is not None

    async def test_incorrect_token_returns_401(self, auth_client: AsyncClient) -> None:
        resp = await auth_client.post("/api/auth/session", json={"token": "wrong-token"})

        assert resp.status_code == 401
        assert SESSION_COOKIE_NAME not in resp.cookies

    async def test_minted_cookie_authenticates_subsequent_request(self, auth_client: AsyncClient) -> None:
        login_resp = await auth_client.post("/api/auth/session", json={"token": TEST_TOKEN})
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

    async def _mint_at(self, token: str, seconds_ago: int) -> str:
        stale_timestamp = int(time.time()) - seconds_ago
        with patch("hassette.web.auth._current_timestamp", return_value=stale_timestamp):
            return mint_session_cookie(token)

    async def test_stale_cookie_gets_renewed(self, auth_client: AsyncClient) -> None:
        # Past half of SESSION_TTL (1800s) but still under the full TTL (3600s).
        stale_cookie = await self._mint_at(TEST_TOKEN, seconds_ago=2000)
        auth_client.cookies.set(SESSION_COOKIE_NAME, stale_cookie)

        resp = await auth_client.get("/api/config")

        assert resp.status_code == 200
        new_value = resp.cookies.get(SESSION_COOKIE_NAME)
        assert new_value is not None
        assert new_value != stale_cookie
        assert verify_session_cookie(new_value, TEST_TOKEN, SESSION_TTL) is not None

    async def test_fresh_cookie_is_not_renewed(self, auth_client: AsyncClient) -> None:
        fresh_cookie = await self._mint_at(TEST_TOKEN, seconds_ago=10)
        auth_client.cookies.set(SESSION_COOKIE_NAME, fresh_cookie)

        resp = await auth_client.get("/api/config")

        assert resp.status_code == 200
        assert resp.cookies.get(SESSION_COOKIE_NAME) is None

    async def test_bearer_authenticated_request_is_not_renewed(self, auth_client: AsyncClient) -> None:
        resp = await auth_client.get("/api/config", headers={"Authorization": f"Bearer {TEST_TOKEN}"})

        assert resp.status_code == 200
        assert resp.cookies.get(SESSION_COOKIE_NAME) is None

    async def test_trusted_proxy_authenticated_request_is_not_renewed(self, auth_hassette) -> None:
        trusted = resolve_trusted_proxies(("203.0.113.5",))
        app = create_fastapi_app(auth_hassette, auth_token=TEST_TOKEN, trusted_proxies=trusted)
        transport = ASGITransport(app=app, client=("203.0.113.5", 12345))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/config")

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
        app = create_fastapi_app(auth_hassette, auth_token=TEST_TOKEN)

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
        hassette.config.web_api.session_ttl = SESSION_TTL
        create_mock_runtime_query_service(hassette)
        return hassette

    async def test_start_app_logs_action_and_source_ip(
        self, mutation_hassette, caplog: pytest.LogCaptureFixture
    ) -> None:
        app = create_fastapi_app(mutation_hassette, auth_token=TEST_TOKEN)
        transport = ASGITransport(app=app, client=("203.0.113.7", 54321))

        with caplog.at_level(logging.INFO, logger="hassette.web.routes.apps"):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/api/apps/my_app/start", headers={"Authorization": f"Bearer {TEST_TOKEN}"})
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
                logs_resp = await client.get("/api/logs/recent", headers={"Authorization": f"Bearer {TEST_TOKEN}"})
                assert logs_resp.status_code == 200
                messages = [r["message"] for r in logs_resp.json()]
                assert any("Started app my_app" in m and "203.0.113.7" in m for m in messages)

    async def test_log_level_change_logs_action_and_source_ip(
        self, mutation_hassette, caplog: pytest.LogCaptureFixture
    ) -> None:
        app = create_fastapi_app(mutation_hassette, auth_token=TEST_TOKEN)
        transport = ASGITransport(app=app, client=("198.51.100.9", 54321))

        with caplog.at_level(logging.INFO, logger="hassette.web.routes.logs"):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.put(
                    "/api/logs/level",
                    json={"logger": "hassette.test_logger", "level": "DEBUG"},
                    headers={"Authorization": f"Bearer {TEST_TOKEN}"},
                )
                assert resp.status_code == 200

        info_records = [r for r in caplog.records if "Changed log level" in r.getMessage()]
        assert len(info_records) == 1
        message = info_records[0].getMessage()
        assert "hassette.test_logger" in message
        assert "198.51.100.9" in message
