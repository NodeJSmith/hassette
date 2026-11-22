"""Integration tests for the WebSocket endpoint (ws.py)."""

import asyncio
import base64
import json
import logging
import os
import socket
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import httpx2
import pytest
import websockets.exceptions
from fastapi import FastAPI
from hassette_wire import ProblemCode, ResourceStatus
from starlette.testclient import TestClient, WebSocketTestSession
from starlette.websockets import WebSocket, WebSocketDisconnect

from hassette.core.runtime_query_service import WS_CLIENT_QUEUE_MAX, RuntimeQueryService
from hassette.schemas.app_snapshots import AppStatusSnapshot
from hassette.schemas.ws_queue import WsClientSignal
from hassette.testing import wait_for
from hassette.testing.config import TEST_SESSION_TTL, WEB_API_TEST_TOKEN
from hassette.web.app import create_fastapi_app
from hassette.web.auth.session import SESSION_COOKIE_NAME, mint_session_cookie
from hassette.web.auth.trusted_proxies import resolve_trusted_proxies
from hassette.web.middleware import FAILED_AUTH_THRESHOLD
from hassette.web.routes.ws import (
    WS_TOO_SLOW_CLOSE_REASON,
    WS_TRY_AGAIN_LATER_CLOSE_CODE,
    WsConnectionState,
    _read_client,
    _send_from_queue,
    websocket_endpoint,
)
from tests.support.helpers import assert_failed_auth_warn_count, capture_failed_auth_warn
from tests.support.uvicorn import start_uvicorn_server, stop_uvicorn_server
from tests.support.web_manifest_helpers import make_app_instance_info
from tests.support.web_mocks import create_hassette_stub, create_mock_runtime_query_service

from .conftest import set_app_status_snapshot, set_websocket_state

LOOPBACK_PEER_IP = "127.0.0.1"
"""The peer address uvicorn reports for the live-server tests' own client, so a `trusted_proxies`
entry naming it makes those connections trusted."""

HANDSHAKE_REJECTED_STATUS = 401
"""HTTP status the websockets client sees when the server rejects the WS handshake pre-accept."""

WS_PATH = "/api/ws"
"""The WebSocket route path, hit by every test in this file — single source of truth so a route
rename only needs to change here."""


@pytest.fixture
def mock_hassette():
    """Create a mock Hassette for WebSocket tests."""
    # 2 running + 1 failed = total_count 3 (matches test assertion app_count == 3)
    running = [
        make_app_instance_info(app_key="app_a", class_name="AppA"),
        make_app_instance_info(app_key="app_b", class_name="AppB"),
    ]
    failed = [
        make_app_instance_info(
            app_key="app_c",
            class_name="AppC",
            status=ResourceStatus.FAILED,
            error=Exception("boom"),
            error_message="boom",
        ),
    ]
    return create_hassette_stub(
        run_web_ui=False,
        cors_origins=(),
        states={"light.kitchen": {"entity_id": "light.kitchen", "state": "on"}},
        old_snapshot=AppStatusSnapshot(instances=(*running, *failed)),
    )


@pytest.fixture
def app(mock_hassette, runtime_query_service):
    fastapi_app = create_fastapi_app(mock_hassette)

    async def _capture_loop():
        runtime_query_service._test_loop = asyncio.get_running_loop()

    fastapi_app.router.on_startup.append(_capture_loop)
    return fastapi_app


@pytest.fixture
def client(app):
    return TestClient(app)


def put_to_all_queues(data_sync: RuntimeQueryService, message: dict) -> None:
    """Put a pre-serialized message into all registered WS client queues.

    The Starlette TestClient runs the ASGI app in a background thread
    with its own event loop.  We use ``call_soon_threadsafe`` to schedule
    the ``put_nowait`` on the correct loop so that any waiting ``get()``
    futures are woken up safely.
    """
    safe = json.loads(json.dumps(message, default=str))
    loop = getattr(data_sync, "_test_loop", None)
    for q in list(data_sync._ws_clients):
        if loop is not None:
            loop.call_soon_threadsafe(q.put_nowait, safe)
        else:
            q.put_nowait(safe)


async def put_on_loop(service: RuntimeQueryService, message: dict) -> None:
    """``put_to_clients`` as a coroutine, for ``run_coroutine_threadsafe`` onto the loop that owns the queues."""
    service.put_to_clients(message)


def sync_via_ping(ws) -> None:
    """Send a ping and wait for the pong to ensure prior messages were processed.

    The server handles ``subscribe`` and ``ping`` sequentially in the same
    reader coroutine, so receiving the ``pong`` guarantees the preceding
    ``subscribe`` has already been applied.
    """
    ws.send_json({"type": "ping"})
    msg = ws.receive_json()
    assert msg["type"] == "pong"


def put_message(data_sync: RuntimeQueryService, message_type: str, **data: Any) -> None:
    """Enqueue one ``{"type": ..., "data": {...}}`` frame for every connected WS client."""
    put_to_all_queues(data_sync, {"type": message_type, "data": data})


def expect_message(ws: "WebSocketTestSession", message_type: str) -> dict[str, Any]:
    """Receive the next frame, assert its type, and return its ``data`` payload.

    ``receive_json()`` blocks until a frame arrives, so asserting on the *next* frame is also
    how these tests prove an earlier-enqueued message was filtered out rather than delivered.
    """
    msg = ws.receive_json()
    assert msg["type"] == message_type
    return msg.get("data", {})


@contextmanager
def subscribed_ws(client: "TestClient", **subscribe_data: Any) -> Iterator["WebSocketTestSession"]:
    """Open a WS connection, consume the ``connected`` frame, and apply one ``subscribe``.

    Every subscription test repeats connect / discard-connected / subscribe / ping-sync before it
    gets to the behavior it actually cares about. Pass no kwargs to skip the subscribe entirely
    (the "default subscription state" cases).
    """
    with client.websocket_connect(WS_PATH) as ws:
        ws.receive_json()  # connected
        if subscribe_data:
            ws.send_json({"type": "subscribe", "data": subscribe_data})
            sync_via_ping(ws)
        yield ws


class TestWebSocketConnection:
    def test_connect_receives_connected_message(self, client: "TestClient") -> None:
        with client.websocket_connect(WS_PATH) as ws:
            msg = ws.receive_json()
            assert msg["type"] == "connected"
            assert msg["data"]["entity_count"] == 1
            assert msg["data"]["app_count"] == 3

    def test_connect_reports_zero_apps_before_bootstrap(self, client: "TestClient", mock_hassette) -> None:
        """The connected payload reports app_count=0 before AppHandler bootstraps any apps.

        The websocket handshake must not require any live app instances — RuntimeQueryService's
        registry reads and system-status derivation are independent of AppHandler readiness.
        """
        set_websocket_state(mock_hassette, connected=False, ever_connected=False)
        set_app_status_snapshot(mock_hassette, running=[], failed=[])
        with client.websocket_connect(WS_PATH) as ws:
            msg = ws.receive_json()
            assert msg["type"] == "connected"
            assert msg["data"]["app_count"] == 0

    def test_ping_pong(self, client: "TestClient") -> None:
        with subscribed_ws(client) as ws:
            sync_via_ping(ws)

    def test_subscribe_logs_enables_log_forwarding(
        self, client: "TestClient", runtime_query_service: RuntimeQueryService
    ) -> None:
        with subscribed_ws(client, logs=True) as ws:
            put_message(runtime_query_service, "log_hint")

            expect_message(ws, "log_hint")

    def test_log_messages_blocked_when_not_subscribed(
        self, client: "TestClient", runtime_query_service: RuntimeQueryService
    ) -> None:
        with subscribed_ws(client) as ws:
            # log_hint should be filtered (subscribe_logs is False by default)
            put_message(runtime_query_service, "log_hint")
            # Non-log message to verify the connection is alive
            put_message(runtime_query_service, "app_status_changed", app_key="my_app")

            expect_message(ws, "app_status_changed")

    def test_non_log_messages_pass_through_without_subscription(
        self, client: "TestClient", runtime_query_service: RuntimeQueryService
    ) -> None:
        with subscribed_ws(client) as ws:
            put_message(runtime_query_service, "app_status_changed", app_key="my_app")

            expect_message(ws, "app_status_changed")

    def test_sentinel_causes_graceful_close(
        self, client: "TestClient", runtime_query_service: RuntimeQueryService
    ) -> None:
        with subscribed_ws(client):
            assert len(runtime_query_service._ws_clients) == 1
            # Send the shutdown signal to trigger graceful queue shutdown
            for q in list(runtime_query_service._ws_clients):
                q.put_nowait(WsClientSignal.SHUTDOWN)
            # The send loop will break on SHUTDOWN, causing the task group to end.
        # After close, client should be unregistered
        assert len(runtime_query_service._ws_clients) == 0

    def test_overflowing_client_is_closed_with_try_again_later(
        self, client: "TestClient", runtime_query_service: RuntimeQueryService
    ) -> None:
        """A client whose queue overflows is closed with 1013 instead of silently missing messages."""
        with subscribed_ws(client) as ws:
            assert len(runtime_query_service._ws_clients) == 1

            async def _overflow() -> None:
                # No await yields to the send loop between broadcasts, so the queue fills and overflows.
                for i in range(WS_CLIENT_QUEUE_MAX + 1):
                    runtime_query_service.put_to_clients({"type": "app_status_changed", "data": {"index": i}})

            # Run on the server's event loop, where the send loop reads the queue.
            ws.portal.call(_overflow)

            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_json()
            assert exc_info.value.code == WS_TRY_AGAIN_LATER_CLOSE_CODE
        assert len(runtime_query_service._ws_clients) == 0

    def test_disconnect_unregisters_client(
        self, client: "TestClient", runtime_query_service: RuntimeQueryService
    ) -> None:
        with subscribed_ws(client):
            assert len(runtime_query_service._ws_clients) == 1
        # After disconnect, client should be unregistered
        assert len(runtime_query_service._ws_clients) == 0

    def test_multiple_subscribe_updates_state(
        self, client: "TestClient", runtime_query_service: RuntimeQueryService
    ) -> None:
        with subscribed_ws(client, logs=False) as ws:
            # A second subscribe replaces the first: log_hint should now pass through.
            ws.send_json({"type": "subscribe", "data": {"logs": True}})
            sync_via_ping(ws)
            put_message(runtime_query_service, "log_hint")

            expect_message(ws, "log_hint")


class TestWebSocketEdgeCases:
    """Edge case tests: invalid messages, unknown types, subscribe with missing/invalid fields."""

    def test_unknown_message_type_connection_stays_open(
        self, client: "TestClient", runtime_query_service: RuntimeQueryService
    ) -> None:
        """Sending an unknown message type is silently ignored; connection stays open."""
        with subscribed_ws(client) as ws:
            ws.send_json({"type": "unknown_type", "data": {}})
            # Verify the connection is still alive by sending ping and receiving pong
            sync_via_ping(ws)

    def test_subscribe_with_missing_fields_uses_defaults(
        self, client: "TestClient", runtime_query_service: RuntimeQueryService
    ) -> None:
        """Subscribe with an empty data dict uses the default: logs=False."""
        with subscribed_ws(client) as ws:
            ws.send_json({"type": "subscribe", "data": {}})
            sync_via_ping(ws)
            # log_hint should NOT pass through (logs=False by default)
            put_message(runtime_query_service, "log_hint")
            # Non-log message confirms connection is alive and log_hint was filtered
            put_message(runtime_query_service, "app_status_changed", app_key="my_app")

            expect_message(ws, "app_status_changed")

    def test_subscribe_with_missing_data_key_uses_defaults(
        self, client: "TestClient", runtime_query_service: RuntimeQueryService
    ) -> None:
        """Subscribe message without a 'data' key treats data as empty dict."""
        with subscribed_ws(client) as ws:
            # Send subscribe without 'data' key at all
            ws.send_json({"type": "subscribe"})
            sync_via_ping(ws)
            # Connection must still be open
            put_message(runtime_query_service, "app_status_changed", app_key="my_app")

            expect_message(ws, "app_status_changed")

    async def test_malformed_json_message_raises_without_crashing_server(self) -> None:
        """Malformed JSON causes _read_client to re-raise JSONDecodeError.

        Starlette's sync TestClient deadlocks when one task-group branch raises
        a non-disconnect exception while the other blocks on the queue, so we
        verify the behavior by calling _read_client directly.
        """
        mock_ws = AsyncMock()
        mock_ws.receive_json = AsyncMock(side_effect=json.JSONDecodeError("bad", "", 0))

        scope = anyio.CancelScope()
        with pytest.raises(json.JSONDecodeError):
            await _read_client(mock_ws, WsConnectionState(), scope)
        assert scope.cancel_called, "a reader error must end the connection's task group"

    async def test_client_disconnect_unregisters_without_further_broadcasts(
        self, mock_hassette: MagicMock, runtime_query_service: RuntimeQueryService
    ) -> None:
        """A client disconnect ends the connection even when nothing is ever broadcast.

        Regression test: the reader returning normally on disconnect must cancel the sender, which
        would otherwise stay blocked on ``queue.get()`` and keep the dead client's queue registered.
        """
        mock_ws = AsyncMock(spec=WebSocket)
        mock_ws.app.state.hassette = mock_hassette
        mock_ws.receive_json = AsyncMock(side_effect=WebSocketDisconnect(code=1000))

        await asyncio.wait_for(websocket_endpoint(mock_ws), timeout=5)

        assert runtime_query_service._ws_clients == set()

    @pytest.mark.parametrize(
        "message",
        [[1, 2, 3], "just a string", 42, {"type": "subscribe", "data": [1]}],
        ids=["array", "string", "number", "subscribe-non-object-data"],
    )
    def test_non_object_message_ignored_connection_stays_open(self, client: "TestClient", message: Any) -> None:
        """A JSON value that isn't an object (or a subscribe with non-object data) is ignored."""
        with subscribed_ws(client) as ws:
            ws.send_json(message)
            sync_via_ping(ws)

    async def test_cancellation_propagates_and_cleans_up(self) -> None:
        """Cancelling the endpoint task propagates CancelledError while still running finally cleanup.

        Regression test: the ``except BaseException`` handler must re-raise
        ``CancelledError`` so shutdown propagation works, while the ``finally``
        block must still call ``unregister_ws_client`` to clean up the queue.
        """
        queue: asyncio.Queue = asyncio.Queue()
        mock_runtime = AsyncMock()
        mock_runtime.register_ws_client.return_value = queue
        mock_runtime.get_system_status = MagicMock(return_value=MagicMock())

        mock_ws = AsyncMock(spec=WebSocket)
        mock_ws.app.state.hassette.runtime_query_service = mock_runtime
        # authorize_ws() (called unconditionally at the top of websocket_endpoint) reads
        # auth_enabled off this mock; an unconfigured Mock attribute is truthy, which would send
        # authorize_ws() further into bearer/cookie checks against other unconfigured Mock
        # attributes and raise before accept() -- unrelated to what this test actually exercises
        # (cancellation/cleanup), so auth is explicitly disabled here.
        mock_ws.app.state.hassette.config.web_api.auth_enabled = False
        mock_ws.accept = AsyncMock()
        mock_ws.send_json = AsyncMock()

        blocked = asyncio.Event()
        hang_forever: asyncio.Future = asyncio.get_running_loop().create_future()

        async def _block():
            blocked.set()
            return await hang_forever

        mock_ws.receive_json = AsyncMock(side_effect=_block)

        mock_data = MagicMock()
        mock_data.model_dump.return_value = {"entity_count": 0}
        with patch("hassette.web.routes.ws.connected_data_from", return_value=mock_data):
            task = asyncio.create_task(websocket_endpoint(mock_ws))
            await blocked.wait()
            assert not task.done(), "endpoint should be blocked waiting for messages"

            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        # The finally block must have called unregister_ws_client with the queue
        mock_runtime.unregister_ws_client.assert_awaited_once_with(queue)

    async def test_stalled_send_closes_with_try_again_later(self) -> None:
        """A send that never completes (the client stopped reading) closes the client with 1013."""
        mock_ws = AsyncMock(spec=WebSocket)
        hang_forever: asyncio.Future = asyncio.get_running_loop().create_future()

        async def _never_sends(_message: dict) -> None:
            await hang_forever

        mock_ws.send_json = AsyncMock(side_effect=_never_sends)
        queue: asyncio.Queue = asyncio.Queue()
        queue.put_nowait({"type": "app_status_changed", "data": {}})

        with patch("hassette.web.routes.ws.WS_SEND_TIMEOUT_SECONDS", 0.05), anyio.CancelScope() as scope:
            await asyncio.wait_for(_send_from_queue(mock_ws, queue, WsConnectionState(), scope), timeout=5)

        mock_ws.close.assert_awaited_once_with(code=WS_TRY_AGAIN_LATER_CLOSE_CODE, reason=WS_TOO_SLOW_CLOSE_REASON)
        assert scope.cancel_called

    async def test_unauthorized_connection_is_denied_before_accept(self) -> None:
        """When `authorize_ws()` returns False, the endpoint sends a 401 denial, counts it, and never accepts.

        Fast, mocked unit-level counterpart to
        `TestWebSocketAuthorization.test_unauthenticated_connection_rejected_before_accept`,
        which requires a real uvicorn server. This test exercises the same routing logic in
        `websocket_endpoint()` (reject before accept) without the live-server overhead, so a
        regression that calls `accept()` before checking `authorize_ws()`, or that swallows the
        early return, is caught by a fast, deterministic test.
        """
        mock_runtime = AsyncMock()
        mock_ws = AsyncMock(spec=WebSocket)
        mock_ws.app.state.hassette.runtime_query_service = mock_runtime
        mock_ws.send_denial_response = AsyncMock()
        mock_ws.accept = AsyncMock()
        mock_ws.client = None
        tracker = mock_ws.app.state.failed_auth = MagicMock()

        with patch("hassette.web.routes.ws.authorize_ws", return_value=False):
            await websocket_endpoint(mock_ws)

        [response] = mock_ws.send_denial_response.await_args.args
        assert response.status_code == 401
        assert json.loads(response.body)["code"] == ProblemCode.NOT_AUTHENTICATED
        tracker.record.assert_called_once_with("unknown")
        mock_ws.accept.assert_not_awaited()
        mock_runtime.register_ws_client.assert_not_awaited()

    def test_unknown_message_type_without_data_key_ignored(self, client: "TestClient") -> None:
        """Unknown message with no 'data' key is silently ignored; connection survives."""
        with subscribed_ws(client) as ws:
            ws.send_json({"type": "whatisthis"})
            # Should still respond to ping
            sync_via_ping(ws)


@pytest.fixture
def auth_hassette() -> MagicMock:
    """A `create_hassette_stub()` with `auth_enabled=True` and a known token, for live-server tests."""
    hassette = create_hassette_stub(
        run_web_ui=False,
        cors_origins=(),
        auth_enabled=True,
        states={"light.kitchen": {"entity_id": "light.kitchen", "state": "on"}},
    )
    hassette.config.web_api.session_ttl = TEST_SESSION_TTL
    create_mock_runtime_query_service(hassette)
    return hassette


@contextmanager
def serve_ws_app(app: FastAPI) -> Iterator[str]:
    """Run `app` under a real uvicorn server for the duration of the block, yielding its `/api/ws` URL.

    `TestClient` (used by every other test in this file) runs the ASGI app in-process via an
    in-memory transport and never exercises uvicorn's actual WebSocket protocol implementation.
    The pre-accept auth check must be verified against the real backend `WebApiService.serve()`
    pins (`ws="websockets-sansio"`, `core/web_api_service.py:71`) -- this is the specific
    empirical verification design.md's Open Questions flagged as unresolved at design time.

    Sits one layer above `start_uvicorn_server`/`stop_uvicorn_server`: those own the port/thread
    lifecycle, this owns the backend pins and URL shape every live WS fixture here needs, so a
    second fixture doesn't have to restate them.
    """
    # Short graceful shutdown: a still-open `websockets.connect()` client can hold the
    # connection past test end, and this backend does not release it quickly on its own
    # (see conftest.py's live_server_ws, which needs the same setting for the same reason).
    server, thread, port = start_uvicorn_server(app, ws="websockets-sansio", timeout_graceful_shutdown=1)
    try:
        yield f"ws://127.0.0.1:{port}{WS_PATH}"
    finally:
        stop_uvicorn_server(server, thread)


@pytest.fixture
def live_auth_server(auth_hassette: MagicMock) -> Iterator[str]:
    """A live WS server with auth enabled and no trusted proxies -- every caller needs a credential."""
    with serve_ws_app(create_fastapi_app(auth_hassette, auth_token=WEB_API_TEST_TOKEN)) as url:
        yield url


@pytest.fixture
async def live_trusted_peer_server(auth_hassette: MagicMock) -> AsyncIterator[str]:
    """A live WS server whose `trusted_proxies` matches the loopback test client.

    The client dials `ws://127.0.0.1:<port>`, so uvicorn reports `127.0.0.1` as the raw ASGI peer
    and the trusted-peer branch is genuinely live -- this is the deployment shape where a
    forward-auth proxy shares a host with hassette, and the one where a presented credential and a
    matching peer collide.

    Goes through the real `resolve_trusted_proxies()` rather than constructing a `TrustedProxySet`
    directly, so the entry parses the same way it would from operator config.
    """
    trusted = await resolve_trusted_proxies((LOOPBACK_PEER_IP,))
    app = create_fastapi_app(auth_hassette, auth_token=WEB_API_TEST_TOKEN, trusted_proxies=trusted)
    with serve_ws_app(app) as url:
        yield url


class TestWebSocketAuthorization:
    """Pre-accept auth check against the real uvicorn `websockets-sansio` backend.

    These tests connect with the `websockets` client library over a real TCP socket rather than
    `TestClient`'s in-process ASGI transport, per design.md's Test Strategy ("no existing
    precedent... new coverage") and to actually exercise the backend the Open Questions flagged as
    unverified.
    """

    async def test_unauthenticated_connection_rejected_before_accept(self, live_auth_server: str) -> None:
        """An unauthenticated WS upgrade never reaches `accept()` -- no data can flow.

        The endpoint answers with REST's 401 problem response through the ASGI WebSocket Denial
        Response extension, which uvicorn's `websockets-sansio` backend implements (0.52.1 and later
        send it as valid HTTP). A browser's native `WebSocket` can't read the status and
        sees `onclose` with code 1006; non-browser clients see the 401.
        """
        with pytest.raises(websockets.exceptions.InvalidStatus) as exc_info:
            async with websockets.connect(live_auth_server, open_timeout=5):
                pass

        assert exc_info.value.response.status_code == HANDSHAKE_REJECTED_STATUS
        assert exc_info.value.response.headers.get_all("Content-Type") == ["application/problem+json"]
        assert json.loads(exc_info.value.response.body)["code"] == ProblemCode.NOT_AUTHENTICATED

    async def test_ws_and_http_failures_share_one_failed_auth_count(
        self, auth_hassette: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Rejected handshakes count toward the same coalesced WARN as REST's 401s from the same source."""
        app = create_fastapi_app(auth_hassette, auth_token=WEB_API_TEST_TOKEN)
        with serve_ws_app(app) as url, capture_failed_auth_warn(caplog):
            for _ in range(FAILED_AUTH_THRESHOLD - 1):
                with pytest.raises(websockets.exceptions.InvalidStatus):
                    async with websockets.connect(url, open_timeout=5):
                        pass
            assert_failed_auth_warn_count(caplog, 0)
            http_url = url.replace("ws://", "http://").removesuffix(WS_PATH) + "/api/config"
            async with httpx2.AsyncClient() as http:
                assert (await http.get(http_url)).status_code == 401

        assert_failed_auth_warn_count(caplog, 1)

    async def test_valid_session_cookie_is_accepted(self, live_auth_server: str) -> None:
        cookie_value = mint_session_cookie(WEB_API_TEST_TOKEN)
        async with websockets.connect(
            live_auth_server,
            additional_headers={"Cookie": f"{SESSION_COOKIE_NAME}={cookie_value}"},
            open_timeout=5,
        ) as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            data = json.loads(msg)
            assert data["type"] == "connected"

    async def test_valid_bearer_header_is_accepted(self, live_auth_server: str) -> None:
        """Non-browser clients (CLI, scripts) authenticate via `Authorization: Bearer <token>`,
        attached through the `websockets` library's `additional_headers` parameter at connect
        time -- new test coverage, no existing precedent for a non-browser WS auth test in this
        repo (design.md Test Strategy).
        """
        async with websockets.connect(
            live_auth_server,
            additional_headers={"Authorization": f"Bearer {WEB_API_TEST_TOKEN}"},
            open_timeout=5,
        ) as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            data = json.loads(msg)
            assert data["type"] == "connected"


class TestWebSocketTrustedPeerPrecedence:
    """A presented `Authorization` header is validated even when the peer matches
    `trusted_proxies` -- pinned end-to-end against the real uvicorn backend.

    `authorize_ws`'s precedence is already unit-tested against a `MagicMock` stand-in in
    `tests/unit/web/test_auth.py`, where the peer address is a fixture value. These tests close the
    remaining gap: the peer address comes from uvicorn over a real TCP handshake, so a regression in
    how the peer is *read* -- not just how it is compared -- surfaces here.

    Rejection arrives as an HTTP 401 handshake failure. See
    `TestWebSocketAuthorization.test_unauthenticated_connection_rejected_before_accept`.
    """

    async def test_no_authorization_header_from_trusted_peer_is_accepted(self, live_trusted_peer_server: str) -> None:
        """Peer trust still admits a caller presenting nothing -- the browser-behind-a-proxy path."""
        async with websockets.connect(live_trusted_peer_server, open_timeout=5) as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            assert json.loads(msg)["type"] == "connected"

    async def test_correct_bearer_token_from_trusted_peer_is_accepted(self, live_trusted_peer_server: str) -> None:
        async with websockets.connect(
            live_trusted_peer_server,
            additional_headers={"Authorization": f"Bearer {WEB_API_TEST_TOKEN}"},
            open_timeout=5,
        ) as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            assert json.loads(msg)["type"] == "connected"

    @pytest.mark.parametrize(
        "header_value",
        [
            "Bearer wrong-token",
            f"Basic {WEB_API_TEST_TOKEN}",
            "Bearer ",
        ],
        ids=["wrong-token", "unrecognized-scheme", "empty-token-value"],
    )
    async def test_invalid_authorization_header_from_trusted_peer_is_rejected(
        self, live_trusted_peer_server: str, header_value: str
    ) -> None:
        """The peer match does not rescue a header the caller chose to present.

        The handshake is rejected before `accept()`, so no application data reaches the caller --
        the same security property the unauthenticated case relies on.
        """
        with pytest.raises(websockets.exceptions.InvalidStatus) as exc_info:
            async with websockets.connect(
                live_trusted_peer_server,
                additional_headers={"Authorization": header_value},
                open_timeout=5,
            ):
                pass

        assert exc_info.value.response.status_code == HANDSHAKE_REJECTED_STATUS


class TestNonReadingClientAgainstLiveServer:
    """A client that stops reading is closed by the send deadline, not buffered without bound.

    The deadline in `_send_from_queue` only fires if `websocket.send_json` blocks once the client stops
    draining its socket, which needs write flow control in uvicorn's `websockets-sansio` backend
    (uvicorn>=0.52.1). The in-process `AsyncMock` test cannot show that; this one runs the real backend.
    """

    SEND_TIMEOUT_SECONDS = 0.3
    CLIENT_RCVBUF_BYTES = 4096
    PAYLOAD_BYTES = 128 * 1024
    QUEUE_HEADROOM = 56
    """Broadcasts stay this far below the client queue's capacity, so overflow can never close the client."""
    BROADCAST_COUNT = WS_CLIENT_QUEUE_MAX - QUEUE_HEADROOM
    CLOSE_DEADLINE_SECONDS = 15.0

    async def test_non_reading_client_is_closed_by_send_deadline(
        self,
        app: FastAPI,
        runtime_query_service: RuntimeQueryService,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr("hassette.web.routes.ws.WS_SEND_TIMEOUT_SECONDS", self.SEND_TIMEOUT_SECONDS)
        caplog.set_level(logging.WARNING, logger="hassette.web.routes.ws")
        loops: list[asyncio.AbstractEventLoop] = []
        server, thread, port = start_uvicorn_server(
            app,
            ws="websockets-sansio",
            timeout_graceful_shutdown=1,
            on_startup=lambda: loops.append(asyncio.get_running_loop()),
        )
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # Set before connect so the advertised TCP window stays small.
            client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self.CLIENT_RCVBUF_BYTES)
            client.settimeout(5)
            client.connect(("127.0.0.1", port))
            handshake_key = base64.b64encode(os.urandom(16)).decode()
            client.sendall(
                (
                    f"GET {WS_PATH} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n"
                    f"Connection: Upgrade\r\nSec-WebSocket-Key: {handshake_key}\r\n"
                    "Sec-WebSocket-Version: 13\r\n\r\n"
                ).encode()
            )
            assert b" 101 " in client.recv(self.CLIENT_RCVBUF_BYTES), "handshake was not accepted"
            # The client never reads again.

            await wait_for(lambda: len(runtime_query_service._ws_clients) == 1, desc="client registered")

            # put_to_clients() runs on the server's loop, which owns the client queue.
            payload = {"type": "app_status_changed", "data": {"blob": "x" * self.PAYLOAD_BYTES}}
            for _ in range(self.BROADCAST_COUNT):
                if not runtime_query_service._ws_clients:
                    break
                await asyncio.wrap_future(
                    asyncio.run_coroutine_threadsafe(put_on_loop(runtime_query_service, payload), loops[0])
                )

            await wait_for(
                lambda: not runtime_query_service._ws_clients,
                timeout=self.CLOSE_DEADLINE_SECONDS,
                desc="non-reading client closed and unregistered",
            )
            assert any("accepted no data" in r.getMessage() for r in caplog.records), (
                "client was unregistered, but not by the send deadline"
            )
        finally:
            client.close()
            stop_uvicorn_server(server, thread)
