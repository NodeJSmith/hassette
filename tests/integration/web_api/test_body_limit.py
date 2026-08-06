"""Tests for the request-body size ceiling (`hassette.web.body_limit`).

From an external security audit at 4a20fb95 (CWE-400): `POST /api/auth/session` is exempt from
`DefaultDenyMiddleware` by design — it is the one route that must be reachable with zero prior
credential — and neither the FastAPI app nor uvicorn imposed a body limit, so an unauthenticated
peer could drive arbitrary pre-authentication allocation. The audit reached the handler with an
8 MiB token and got the route's normal 401 back.

Two of these tests run against a **real uvicorn server** rather than `ASGITransport`, for reasons
the in-process transport cannot cover:

- `ASGITransport` never exercises uvicorn's own HTTP framing, so a `413` proven only in-process
  says nothing about whether the deployed server also rejects.
- The chunked case has no `Content-Length` at all, which means it can only be produced by a client
  talking real HTTP. It is the bypass that makes a header-only check insufficient, so it needs the
  real transport to be meaningful.
"""

import json

import httpx2
import pytest
from httpx2 import AsyncClient

from hassette.test_utils.config import WEB_API_TEST_TOKEN
from hassette.test_utils.uvicorn_server import start_uvicorn_server, stop_uvicorn_server
from hassette.web.body_limit import MAX_REQUEST_BODY_BYTES, RequestBodySizeLimitMiddleware
from hassette.web.models import MAX_SESSION_TOKEN_LENGTH

# `auth_hassette`, `auth_app`, and `auth_client` come from this directory's conftest.py.


def _oversized_token() -> str:
    """A token comfortably past the body ceiling, not merely past the field's max_length.

    Sized from the ceiling rather than from `MAX_SESSION_TOKEN_LENGTH` on purpose: the point is to
    prove the *body* limit fires, and a value that only trips the field validator would produce a
    422 from Pydantic after the body was already buffered — the exact allocation being prevented.
    """
    return "A" * (MAX_REQUEST_BODY_BYTES * 2)


class TestBodyCeilingInProcess:
    """Ceiling behavior through the ASGI transport, where the declared Content-Length is present."""

    async def test_oversized_body_returns_413(self, auth_client: AsyncClient) -> None:
        response = await auth_client.post("/api/auth/session", json={"token": _oversized_token()})

        assert response.status_code == 413
        assert response.json() == {"detail": "Request body too large"}

    async def test_413_advertises_the_ceiling(self, auth_client: AsyncClient) -> None:
        """A rejected client gets the limit back, rather than having to bisect payload sizes."""
        response = await auth_client.post("/api/auth/session", json={"token": _oversized_token()})

        assert response.headers["x-max-body-bytes"] == str(MAX_REQUEST_BODY_BYTES)

    async def test_oversized_body_with_correct_token_still_rejected(self, auth_client: AsyncClient) -> None:
        """The ceiling precedes the credential check, so a valid token buried in bulk gains nothing.

        This is the behavioral proof that the handler never ran: had it executed, a correct token
        would have minted a session cookie.
        """
        padded = WEB_API_TEST_TOKEN + "A" * (MAX_REQUEST_BODY_BYTES * 2)
        response = await auth_client.post("/api/auth/session", json={"token": padded})

        assert response.status_code == 413
        assert "set-cookie" not in response.headers

    async def test_normal_login_below_the_limit_is_unaffected(self, auth_client: AsyncClient) -> None:
        response = await auth_client.post("/api/auth/session", json={"token": WEB_API_TEST_TOKEN})

        assert response.status_code == 200
        assert "set-cookie" in response.headers

    async def test_wrong_token_below_the_limit_still_401s(self, auth_client: AsyncClient) -> None:
        """The ceiling must not swallow the route's own auth semantics for ordinary payloads."""
        response = await auth_client.post("/api/auth/session", json={"token": "wrong-token"})

        assert response.status_code == 401

    async def test_body_just_under_the_ceiling_reaches_the_handler(self, auth_client: AsyncClient) -> None:
        """A payload under the ceiling is handled normally — here, rejected on token mismatch (401),
        not on size. Pins that the boundary is not off by enough to catch legitimate traffic.
        """
        token = "A" * (MAX_SESSION_TOKEN_LENGTH - 1)
        response = await auth_client.post("/api/auth/session", json={"token": token})

        assert response.status_code == 401

    async def test_token_past_field_max_length_is_a_validation_error(self, auth_client: AsyncClient) -> None:
        """Between the field cap and the body ceiling, Pydantic answers 422 — not 413, not 401."""
        token = "A" * (MAX_SESSION_TOKEN_LENGTH + 1)
        response = await auth_client.post("/api/auth/session", json={"token": token})

        assert response.status_code == 422

    async def test_gated_route_body_is_still_gated_not_413(self, auth_client: AsyncClient) -> None:
        """An authenticated-route request with a small body keeps its 401, not a size error."""
        response = await auth_client.put("/api/logs/level", json={"logger": "hassette", "level": "DEBUG"})

        assert response.status_code == 401


class TestBodyCeilingAgainstRealServer:
    """Ceiling behavior against real uvicorn, including the no-Content-Length bypass."""

    @pytest.fixture
    def live_server(self, auth_app):
        server, thread, port = start_uvicorn_server(auth_app)
        try:
            yield f"http://127.0.0.1:{port}"
        finally:
            stop_uvicorn_server(server, thread)

    async def test_oversized_body_rejected_by_real_server(self, live_server: str) -> None:
        """The audit's own reproduction, inverted: an oversized token now gets 413, not the 401 it
        previously got after reaching the handler.
        """
        async with httpx2.AsyncClient(base_url=live_server, timeout=10) as client:
            response = await client.post("/api/auth/session", json={"token": _oversized_token()})

        assert response.status_code == 413

    async def test_chunked_oversized_body_rejected_by_real_server(self, live_server: str) -> None:
        """A streamed body with no Content-Length is still bounded, with the documented 413.

        This is the case a header-only check misses entirely: httpx2 switches to
        `Transfer-Encoding: chunked` for an async-generator body, so the ceiling can only be
        enforced by counting bytes as they arrive. The middleware buffers the body itself and
        decides pass/reject before the downstream app (and FastAPI's own body parsing) ever runs,
        so the reject is a deterministic 413 rather than racing FastAPI's generic 400 for a body
        error — see body_limit.py's `_buffer_body` docstring for why that race existed before.
        """
        payload = json.dumps({"token": _oversized_token()}).encode()

        async def chunks():
            for start in range(0, len(payload), 8192):
                yield payload[start : start + 8192]

        async with httpx2.AsyncClient(base_url=live_server, timeout=10) as client:
            response = await client.post(
                "/api/auth/session",
                content=chunks(),
                headers={"content-type": "application/json"},
            )

        assert response.status_code == 413
        assert response.headers["x-max-body-bytes"] == str(MAX_REQUEST_BODY_BYTES)
        assert "set-cookie" not in response.headers

    async def test_normal_login_against_real_server_unaffected(self, live_server: str) -> None:
        async with httpx2.AsyncClient(base_url=live_server, timeout=10) as client:
            response = await client.post("/api/auth/session", json={"token": WEB_API_TEST_TOKEN})

        assert response.status_code == 200


class TestNonHttpScopesPassThrough:
    """The ceiling applies to HTTP only; other ASGI scope types are none of its business."""

    async def test_health_get_with_no_body_is_unaffected(self, auth_client: AsyncClient) -> None:
        response = await auth_client.get("/api/health/live")

        assert response.status_code == 200

    async def test_middleware_leaves_websocket_scope_alone(self, auth_hassette) -> None:
        """A `websocket` scope reaches the app untouched rather than being treated as HTTP.

        Asserted at the middleware level: `RequestBodySizeLimitMiddleware` must delegate without
        inspecting headers, since a WS scope has no request body to bound and frame limits belong
        to the transport.
        """
        seen: list[str] = []

        async def app(scope, _receive, _send) -> None:
            seen.append(scope["type"])

        middleware = RequestBodySizeLimitMiddleware(app)
        await middleware({"type": "websocket", "headers": []}, None, None)  # pyright: ignore[reportArgumentType]

        assert seen == ["websocket"]
