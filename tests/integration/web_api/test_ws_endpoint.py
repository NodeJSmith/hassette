"""Integration tests for the WebSocket endpoint (ws.py)."""

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import websockets.exceptions
from fastapi import FastAPI
from starlette.websockets import WebSocket

from hassette.core.runtime_query_service import RuntimeQueryService
from hassette.schemas.app_snapshots import AppInstanceInfo, AppStatusSnapshot
from hassette.test_utils.config import TEST_SESSION_TTL, WEB_API_TEST_TOKEN
from hassette.test_utils.uvicorn_server import start_uvicorn_server, stop_uvicorn_server
from hassette.test_utils.web_mocks import create_hassette_stub, create_mock_runtime_query_service
from hassette.types.enums import ResourceStatus
from hassette.web.app import create_fastapi_app
from hassette.web.auth.session import SESSION_COOKIE_NAME, mint_session_cookie
from hassette.web.auth.trusted_proxies import resolve_trusted_proxies
from hassette.web.routes.ws import _read_client, websocket_endpoint

from .conftest import set_app_status_snapshot, set_websocket_state

try:
    from starlette.testclient import TestClient

    HAS_STARLETTE_TC = True
except ImportError:
    HAS_STARLETTE_TC = False

pytestmark = pytest.mark.skipif(not HAS_STARLETTE_TC, reason="starlette testclient not available")

LOOPBACK_PEER_IP = "127.0.0.1"
"""The peer address uvicorn reports for the live-server tests' own client, so a `trusted_proxies`
entry naming it makes those connections trusted."""

WS_PATH = "/api/ws"
"""The WebSocket route path, hit by every test in this file — single source of truth so a route
rename only needs to change here."""


@pytest.fixture
def mock_hassette():
    """Create a mock Hassette for WebSocket tests."""
    # 2 running + 1 failed = total_count 3 (matches test assertion app_count == 3)
    running = [
        AppInstanceInfo(
            app_key="app_a",
            index=0,
            instance_name="AppA[0]",
            class_name="AppA",
            status=ResourceStatus.RUNNING,
        ),
        AppInstanceInfo(
            app_key="app_b",
            index=0,
            instance_name="AppB[0]",
            class_name="AppB",
            status=ResourceStatus.RUNNING,
        ),
    ]
    failed = [
        AppInstanceInfo(
            app_key="app_c",
            index=0,
            instance_name="AppC[0]",
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
        old_snapshot=AppStatusSnapshot(instances=running + failed),
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


def sync_via_ping(ws) -> None:
    """Send a ping and wait for the pong to ensure prior messages were processed.

    The server handles ``subscribe`` and ``ping`` sequentially in the same
    reader coroutine, so receiving the ``pong`` guarantees the preceding
    ``subscribe`` has already been applied.
    """
    ws.send_json({"type": "ping"})
    msg = ws.receive_json()
    assert msg["type"] == "pong"


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
        with client.websocket_connect(WS_PATH) as ws:
            ws.receive_json()  # consume connected message
            ws.send_json({"type": "ping"})
            msg = ws.receive_json()
            assert msg["type"] == "pong"

    def test_subscribe_logs_enables_log_forwarding(
        self, client: "TestClient", runtime_query_service: RuntimeQueryService
    ) -> None:
        with client.websocket_connect(WS_PATH) as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "subscribe", "data": {"logs": True}})
            sync_via_ping(ws)
            put_to_all_queues(
                runtime_query_service,
                {"type": "log", "data": {"level": "INFO", "message": "test"}},
            )
            msg = ws.receive_json()
            assert msg["type"] == "log"
            assert msg["data"]["message"] == "test"

    def test_log_messages_blocked_when_not_subscribed(
        self, client: "TestClient", runtime_query_service: RuntimeQueryService
    ) -> None:
        with client.websocket_connect(WS_PATH) as ws:
            ws.receive_json()  # connected
            # Log should be filtered (subscribe_logs is False by default)
            put_to_all_queues(
                runtime_query_service,
                {"type": "log", "data": {"level": "INFO", "message": "should not arrive"}},
            )
            # Non-log message to verify the connection is alive
            put_to_all_queues(
                runtime_query_service,
                {"type": "state_changed", "data": {"entity_id": "light.kitchen"}},
            )
            msg = ws.receive_json()
            assert msg["type"] == "state_changed"

    def test_non_log_messages_pass_through_without_subscription(
        self, client: "TestClient", runtime_query_service: RuntimeQueryService
    ) -> None:
        with client.websocket_connect(WS_PATH) as ws:
            ws.receive_json()  # connected
            put_to_all_queues(
                runtime_query_service,
                {"type": "app_status_changed", "data": {"app_key": "my_app"}},
            )
            msg = ws.receive_json()
            assert msg["type"] == "app_status_changed"

    def test_subscribe_min_log_level_filters_below_threshold(
        self, client: "TestClient", runtime_query_service: RuntimeQueryService
    ) -> None:
        with client.websocket_connect(WS_PATH) as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "subscribe", "data": {"logs": True, "min_log_level": "WARNING"}})
            sync_via_ping(ws)
            # DEBUG and INFO should be filtered
            put_to_all_queues(
                runtime_query_service,
                {"type": "log", "data": {"level": "DEBUG", "message": "debug"}},
            )
            put_to_all_queues(
                runtime_query_service,
                {"type": "log", "data": {"level": "INFO", "message": "info"}},
            )
            # WARNING should pass
            put_to_all_queues(
                runtime_query_service,
                {"type": "log", "data": {"level": "WARNING", "message": "warn"}},
            )
            msg = ws.receive_json()
            assert msg["type"] == "log"
            assert msg["data"]["level"] == "WARNING"

    def test_subscribe_error_level_passes(
        self, client: "TestClient", runtime_query_service: RuntimeQueryService
    ) -> None:
        with client.websocket_connect(WS_PATH) as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "subscribe", "data": {"logs": True, "min_log_level": "ERROR"}})
            sync_via_ping(ws)
            put_to_all_queues(
                runtime_query_service,
                {"type": "log", "data": {"level": "WARNING", "message": "warn"}},
            )
            put_to_all_queues(
                runtime_query_service,
                {"type": "log", "data": {"level": "ERROR", "message": "err"}},
            )
            # receive_json() blocks until a message arrives.  Since the
            # WARNING was enqueued *before* the ERROR, the fact that the next
            # (and only) message we receive is ERROR proves the WARNING was
            # filtered out by the min_log_level subscription.
            msg = ws.receive_json()
            assert msg["type"] == "log"
            assert msg["data"]["level"] == "ERROR"

    def test_subscribe_invalid_log_level_defaults_to_info(
        self, client: "TestClient", runtime_query_service: RuntimeQueryService
    ) -> None:
        with client.websocket_connect(WS_PATH) as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "subscribe", "data": {"logs": True, "min_log_level": "INVALID"}})
            sync_via_ping(ws)
            # DEBUG should be filtered (below INFO default)
            put_to_all_queues(
                runtime_query_service,
                {"type": "log", "data": {"level": "DEBUG", "message": "debug"}},
            )
            # INFO should pass
            put_to_all_queues(
                runtime_query_service,
                {"type": "log", "data": {"level": "INFO", "message": "info"}},
            )
            msg = ws.receive_json()
            assert msg["type"] == "log"
            assert msg["data"]["level"] == "INFO"

    def test_sentinel_causes_graceful_close(
        self, client: "TestClient", runtime_query_service: RuntimeQueryService
    ) -> None:
        with client.websocket_connect(WS_PATH) as ws:
            ws.receive_json()  # connected
            assert len(runtime_query_service._ws_clients) == 1
            # Send None sentinel to trigger graceful queue shutdown
            for q in list(runtime_query_service._ws_clients):
                q.put_nowait(None)
            # The send loop will break on None, causing the task group to end.
        # After close, client should be unregistered
        assert len(runtime_query_service._ws_clients) == 0

    def test_disconnect_unregisters_client(
        self, client: "TestClient", runtime_query_service: RuntimeQueryService
    ) -> None:
        with client.websocket_connect(WS_PATH) as ws:
            ws.receive_json()  # connected
            assert len(runtime_query_service._ws_clients) == 1
        # After disconnect, client should be unregistered
        assert len(runtime_query_service._ws_clients) == 0

    def test_multiple_subscribe_updates_state(
        self, client: "TestClient", runtime_query_service: RuntimeQueryService
    ) -> None:
        with client.websocket_connect(WS_PATH) as ws:
            ws.receive_json()  # connected
            # First subscribe with ERROR level
            ws.send_json({"type": "subscribe", "data": {"logs": True, "min_log_level": "ERROR"}})
            sync_via_ping(ws)
            # Update to INFO level
            ws.send_json({"type": "subscribe", "data": {"logs": True, "min_log_level": "INFO"}})
            sync_via_ping(ws)
            # INFO should now pass through
            put_to_all_queues(
                runtime_query_service,
                {"type": "log", "data": {"level": "INFO", "message": "visible"}},
            )
            msg = ws.receive_json()
            assert msg["type"] == "log"
            assert msg["data"]["level"] == "INFO"


class TestWebSocketEdgeCases:
    """Edge case tests: invalid messages, unknown types, subscribe with missing/invalid fields."""

    def test_unknown_message_type_connection_stays_open(
        self, client: "TestClient", runtime_query_service: RuntimeQueryService
    ) -> None:
        """Sending an unknown message type is silently ignored; connection stays open."""
        with client.websocket_connect(WS_PATH) as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "unknown_type", "data": {}})
            # Verify the connection is still alive by sending ping and receiving pong
            ws.send_json({"type": "ping"})
            msg = ws.receive_json()
            assert msg["type"] == "pong"

    def test_subscribe_with_missing_fields_uses_defaults(
        self, client: "TestClient", runtime_query_service: RuntimeQueryService
    ) -> None:
        """Subscribe with an empty data dict uses defaults: logs=False, min_log_level=INFO."""
        with client.websocket_connect(WS_PATH) as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "subscribe", "data": {}})
            sync_via_ping(ws)
            # Log messages should NOT pass through (logs=False by default)
            put_to_all_queues(
                runtime_query_service,
                {"type": "log", "data": {"level": "INFO", "message": "should not arrive"}},
            )
            # Non-log message confirms connection is alive and log was filtered
            put_to_all_queues(
                runtime_query_service,
                {"type": "state_changed", "data": {"entity_id": "light.kitchen"}},
            )
            msg = ws.receive_json()
            assert msg["type"] == "state_changed"

    def test_subscribe_with_missing_data_key_uses_defaults(
        self, client: "TestClient", runtime_query_service: RuntimeQueryService
    ) -> None:
        """Subscribe message without a 'data' key treats data as empty dict."""
        with client.websocket_connect(WS_PATH) as ws:
            ws.receive_json()  # connected
            # Send subscribe without 'data' key at all
            ws.send_json({"type": "subscribe"})
            sync_via_ping(ws)
            # Connection must still be open
            put_to_all_queues(
                runtime_query_service,
                {"type": "app_status_changed", "data": {"app_key": "my_app"}},
            )
            msg = ws.receive_json()
            assert msg["type"] == "app_status_changed"

    async def test_malformed_json_message_raises_without_crashing_server(self) -> None:
        """Malformed JSON causes _read_client to re-raise JSONDecodeError.

        Starlette's sync TestClient deadlocks when one task-group branch raises
        a non-disconnect exception while the other blocks on the queue, so we
        verify the behavior by calling _read_client directly.
        """
        mock_ws = AsyncMock()
        mock_ws.receive_json = AsyncMock(side_effect=json.JSONDecodeError("bad", "", 0))

        ws_state: dict = {}
        with pytest.raises(json.JSONDecodeError):
            await _read_client(mock_ws, ws_state)

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

        mock_payload = MagicMock()
        mock_payload.model_dump.return_value = {"entity_count": 0}
        with patch("hassette.web.routes.ws.connected_payload_from", return_value=mock_payload):
            task = asyncio.create_task(websocket_endpoint(mock_ws))
            await blocked.wait()
            assert not task.done(), "endpoint should be blocked waiting for messages"

            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        # The finally block must have called unregister_ws_client with the queue
        mock_runtime.unregister_ws_client.assert_awaited_once_with(queue)

    async def test_unauthorized_connection_closes_before_accept(self) -> None:
        """When `authorize_ws()` returns False, the endpoint closes with 1008 and never accepts.

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
        mock_ws.close = AsyncMock()
        mock_ws.accept = AsyncMock()

        with patch("hassette.web.routes.ws.authorize_ws", return_value=False):
            await websocket_endpoint(mock_ws)

        mock_ws.close.assert_awaited_once_with(code=1008)
        mock_ws.accept.assert_not_awaited()
        mock_runtime.register_ws_client.assert_not_awaited()

    def test_unknown_message_type_without_data_key_ignored(self, client: "TestClient") -> None:
        """Unknown message with no 'data' key is silently ignored; connection survives."""
        with client.websocket_connect(WS_PATH) as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "whatisthis"})
            # Should still respond to ping
            ws.send_json({"type": "ping"})
            msg = ws.receive_json()
            assert msg["type"] == "pong"


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

        The design specifies the server closes with WS code 1008 before calling `accept()`.
        Empirically confirmed here: under uvicorn's `ws="websockets-sansio"` backend, a pre-accept
        `websocket.close()` ASGI message is never translated into a WebSocket close *frame* on the
        wire at all. `websockets_sansio_impl.py`'s `send()` hardcodes an HTTP 403 Forbidden
        handshake rejection for any pre-accept `websocket.close`
        (`response = self.conn.reject(HTTPStatus.FORBIDDEN, "")`), discarding whatever code the
        application passed. A real client (this test, or a browser's native `WebSocket`) therefore
        never observes close code 1008 -- it sees a failed handshake (403), and a browser's
        `onclose` would fire with code 1006 (abnormal closure) per the WebSocket spec's handling of
        a rejected upgrade. The security property this is actually protecting -- no application
        data reaches an unauthenticated peer, because `accept()` is never called -- does hold; only
        the specific "delivered as WS close code 1008" mechanism does not survive contact with this
        backend. See this task's Verify section / CONTESTED note for the full account.
        """
        with pytest.raises(websockets.exceptions.InvalidStatus) as exc_info:
            async with websockets.connect(live_auth_server, open_timeout=5):
                pass

        assert exc_info.value.response.status_code == 403

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

    Rejection arrives as an HTTP 403 handshake failure rather than WS close code 1008. See
    `TestWebSocketAuthorization.test_unauthenticated_connection_rejected_before_accept` for why this
    backend never puts the application's close code on the wire.
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

        assert exc_info.value.response.status_code == 403
