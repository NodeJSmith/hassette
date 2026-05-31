"""Unit tests for WebsocketService connection state machine (WP03).

Tests for the three-state ConnectionState enum (DISCONNECTED, CONNECTING, CONNECTED),
_set_connection_state() validation, and proper state transitions in serve/connect/cleanup.
"""

import asyncio
import logging
import time
from unittest.mock import AsyncMock, patch

import pytest

from hassette.core.websocket_service import WebsocketService
from hassette.exceptions import InvalidAuthError, InvalidLifecycleTransitionError, RetryableConnectionClosedError
from hassette.test_utils import make_ws_hassette_stub
from hassette.types.enums import ConnectionState


@pytest.fixture
async def websocket_service() -> WebsocketService:
    """Create a WebsocketService with a fully-mocked hassette stub (non-strict mode)."""
    hassette = make_ws_hassette_stub(strict_lifecycle=False, sealed=False)
    return WebsocketService(hassette=hassette)


@pytest.fixture
async def websocket_service_strict() -> WebsocketService:
    """Create a WebsocketService with strict_lifecycle=True."""
    hassette = make_ws_hassette_stub(strict_lifecycle=True, sealed=False)
    return WebsocketService(hassette=hassette)


class TestInitialState:
    async def test_initial_state_disconnected(self, websocket_service: WebsocketService) -> None:
        """New WebsocketService has connection_state == DISCONNECTED."""
        assert websocket_service.connection_state == ConnectionState.DISCONNECTED


class TestConnectedPropertyMirrorsState:
    async def test_connected_true_only_for_connected_state(self, websocket_service: WebsocketService) -> None:
        """connected returns True only when connection_state == CONNECTED."""
        # DISCONNECTED → not connected
        websocket_service._connection_state = ConnectionState.DISCONNECTED
        assert websocket_service.connected is False

        # CONNECTING → not connected
        websocket_service._connection_state = ConnectionState.CONNECTING
        assert websocket_service.connected is False

        # CONNECTED → connected
        websocket_service._connection_state = ConnectionState.CONNECTED
        assert websocket_service.connected is True


class TestValidTransitionTable:
    async def test_disconnected_to_connecting(self, websocket_service: WebsocketService) -> None:
        """DISCONNECTED → CONNECTING is valid."""
        websocket_service._connection_state = ConnectionState.DISCONNECTED
        websocket_service._set_connection_state(ConnectionState.CONNECTING)
        assert websocket_service.connection_state == ConnectionState.CONNECTING

    async def test_connecting_to_connected(self, websocket_service: WebsocketService) -> None:
        """CONNECTING → CONNECTED is valid."""
        websocket_service._connection_state = ConnectionState.CONNECTING
        websocket_service._set_connection_state(ConnectionState.CONNECTED)
        assert websocket_service.connection_state == ConnectionState.CONNECTED

    async def test_connecting_to_disconnected(self, websocket_service: WebsocketService) -> None:
        """CONNECTING → DISCONNECTED is valid (non-retryable failure)."""
        websocket_service._connection_state = ConnectionState.CONNECTING
        websocket_service._set_connection_state(ConnectionState.DISCONNECTED)
        assert websocket_service.connection_state == ConnectionState.DISCONNECTED

    async def test_connected_to_connecting(self, websocket_service: WebsocketService) -> None:
        """CONNECTED → CONNECTING is valid (reconnect)."""
        websocket_service._connection_state = ConnectionState.CONNECTED
        websocket_service._set_connection_state(ConnectionState.CONNECTING)
        assert websocket_service.connection_state == ConnectionState.CONNECTING

    async def test_connected_to_disconnected(self, websocket_service: WebsocketService) -> None:
        """CONNECTED → DISCONNECTED is valid (clean shutdown)."""
        websocket_service._connection_state = ConnectionState.CONNECTED
        websocket_service._set_connection_state(ConnectionState.DISCONNECTED)
        assert websocket_service.connection_state == ConnectionState.DISCONNECTED


class TestInvalidTransitions:
    async def test_invalid_transition_strict(self, websocket_service_strict: WebsocketService) -> None:
        """DISCONNECTED → CONNECTED raises InvalidLifecycleTransitionError in strict mode."""
        websocket_service_strict._connection_state = ConnectionState.DISCONNECTED

        with pytest.raises(InvalidLifecycleTransitionError):
            websocket_service_strict._set_connection_state(ConnectionState.CONNECTED)

        # State unchanged after invalid transition
        assert websocket_service_strict.connection_state == ConnectionState.DISCONNECTED

    async def test_invalid_transition_nonstrict(self, websocket_service: WebsocketService) -> None:
        """DISCONNECTED → CONNECTED logs WARNING in non-strict mode (no raise)."""
        websocket_service._connection_state = ConnectionState.DISCONNECTED

        # Should not raise — non-strict mode only warns
        websocket_service._set_connection_state(ConnectionState.CONNECTED)

        # In non-strict mode the transition is still applied (warn-and-continue)
        # (this matches the lifecycle mixin behavior)
        assert websocket_service.connection_state == ConnectionState.CONNECTED

    async def test_invalid_transition_connected_to_connected_is_noop(
        self, websocket_service_strict: WebsocketService
    ) -> None:
        """CONNECTED → CONNECTED is a no-op (self-transition) even in strict mode."""
        websocket_service_strict._connection_state = ConnectionState.CONNECTED

        # Self-transitions are always silently ignored — they are not invalid transitions
        websocket_service_strict._set_connection_state(ConnectionState.CONNECTED)
        assert websocket_service_strict.connection_state == ConnectionState.CONNECTED


class TestHasattrGuard:
    async def test_invalid_transition_no_hassette_no_crash(self) -> None:
        """Invalid WS transition on an object without hassette must not AttributeError."""
        ws = WebsocketService.__new__(WebsocketService)
        ws._connection_state = ConnectionState.DISCONNECTED
        ws.logger = logging.getLogger("test")

        assert not hasattr(ws, "hassette")
        ws._set_connection_state(ConnectionState.CONNECTED)
        assert ws._connection_state == ConnectionState.CONNECTED


class TestValidConnectSequence:
    async def test_valid_connect_sequence(self, websocket_service: WebsocketService) -> None:
        """DISCONNECTED → CONNECTING → CONNECTED transition sequence via serve()."""
        websocket_service.hassette.send_event = AsyncMock()

        states: list[ConnectionState] = []
        original_set = websocket_service._set_connection_state

        def capture_set(new: ConnectionState) -> None:
            original_set(new)
            states.append(websocket_service.connection_state)

        websocket_service._set_connection_state = capture_set  # pyright: ignore[reportAttributeAccessIssue]

        # Stub _make_connection to succeed on first attempt (clean exit)
        async def fake_make_connection(_session):
            # Simulate _start_recv_and_subscribe setting CONNECTED and marking ready
            websocket_service._set_connection_state(ConnectionState.CONNECTED)
            websocket_service.mark_ready(reason="test: connected")

            async def _clean():
                pass

            return asyncio.create_task(_clean())

        websocket_service._make_connection = fake_make_connection  # pyright: ignore[reportAttributeAccessIssue]

        await websocket_service.serve()

        # Must have transitioned through CONNECTING → CONNECTED
        assert ConnectionState.CONNECTING in states
        assert ConnectionState.CONNECTED in states
        # CONNECTING must precede CONNECTED
        connecting_idx = next(i for i, s in enumerate(states) if s == ConnectionState.CONNECTING)
        connected_idx = next(i for i, s in enumerate(states) if s == ConnectionState.CONNECTED)
        assert connecting_idx < connected_idx


class TestReconnectSequence:
    async def test_reconnect_sequence(self, websocket_service: WebsocketService) -> None:
        """CONNECTED → CONNECTING → CONNECTED on connection lost and retried."""
        websocket_service.hassette.send_event = AsyncMock()

        states: list[ConnectionState] = []
        original_set = websocket_service._set_connection_state

        def capture_set(new: ConnectionState) -> None:
            original_set(new)
            states.append(websocket_service.connection_state)

        websocket_service._set_connection_state = capture_set  # pyright: ignore[reportAttributeAccessIssue]

        call_count = 0

        async def fake_make_connection(_session):
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                # First: successful connection, then early drop
                websocket_service._set_connection_state(ConnectionState.CONNECTED)
                websocket_service._connected_at = time.monotonic()
                websocket_service.mark_ready(reason="test: connected")

                async def _fail():
                    raise RetryableConnectionClosedError("peer gone")

                return asyncio.create_task(_fail())

            # Second: clean exit (reconnect succeeded)
            websocket_service._set_connection_state(ConnectionState.CONNECTED)
            websocket_service.mark_ready(reason="test: reconnected")

            async def _clean():
                pass

            return asyncio.create_task(_clean())

        websocket_service._make_connection = fake_make_connection  # pyright: ignore[reportAttributeAccessIssue]
        websocket_service._partial_cleanup = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

        await websocket_service.serve()

        # Expected sequence: CONNECTING (initial), CONNECTED (first connect),
        # CONNECTING (reconnect attempt), CONNECTED (reconnect success)
        connecting_count = states.count(ConnectionState.CONNECTING)
        connected_count = states.count(ConnectionState.CONNECTED)

        assert connecting_count >= 2, f"Expected at least 2 CONNECTING transitions, got {connecting_count}: {states}"
        assert connected_count >= 2, f"Expected at least 2 CONNECTED transitions, got {connected_count}: {states}"


class TestAuthFailureDisconnects:
    async def test_auth_failure_disconnects(self, websocket_service: WebsocketService) -> None:
        """serve() sets DISCONNECTED when InvalidAuthError propagates (non-retryable failure)."""
        websocket_service.hassette.send_event = AsyncMock()

        async def fake_make_connection(_session):
            raise InvalidAuthError("bad token")

        websocket_service._make_connection = fake_make_connection  # pyright: ignore[reportAttributeAccessIssue]

        with pytest.raises(InvalidAuthError):
            await websocket_service.serve()

        assert websocket_service.connection_state == ConnectionState.DISCONNECTED


class TestMaxRetriesDisconnects:
    async def test_max_retries_disconnects(self, websocket_service: WebsocketService) -> None:
        """serve() sets DISCONNECTED when max early-drop retries are exhausted."""
        websocket_service.hassette.send_event = AsyncMock()

        call_count = 0

        async def fake_make_connection(_session):
            nonlocal call_count
            call_count += 1
            websocket_service._connected_at = time.monotonic()
            websocket_service.mark_ready(reason="test: simulating successful connection")

            async def _fail():
                raise RetryableConnectionClosedError("dropped")

            return asyncio.create_task(_fail())

        websocket_service._make_connection = fake_make_connection  # pyright: ignore[reportAttributeAccessIssue]
        websocket_service._partial_cleanup = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
        websocket_service.hassette.config.websocket.early_drop_max_retries = 1
        websocket_service.hassette.config.websocket.early_drop_stable_window_seconds = 30.0
        websocket_service.hassette.config.websocket.early_drop_backoff_initial_seconds = 0.001
        websocket_service.hassette.config.websocket.early_drop_backoff_max_seconds = 0.01

        with pytest.raises(RetryableConnectionClosedError):
            await websocket_service.serve()

        assert websocket_service.connection_state == ConnectionState.DISCONNECTED


class TestCleanShutdownDisconnects:
    async def test_clean_shutdown_disconnects(self, websocket_service: WebsocketService) -> None:
        """cleanup() sets DISCONNECTED at the start (clean shutdown path)."""
        # First put service into CONNECTED state
        websocket_service._connection_state = ConnectionState.CONNECTED

        # Stub everything cleanup touches
        websocket_service._ws = None
        websocket_service._session = None
        websocket_service._recv_task = None

        # Patch the parent cleanup to avoid issues with mock hassette
        with patch.object(type(websocket_service).__bases__[0], "cleanup", new=AsyncMock()):
            await websocket_service.cleanup()

        assert websocket_service.connection_state == ConnectionState.DISCONNECTED


class TestPartialCleanupNoStateChange:
    async def test_partial_cleanup_no_state_change(self, websocket_service: WebsocketService) -> None:
        """_partial_cleanup() does NOT change connection_state."""
        # Put into CONNECTED state
        websocket_service._connection_state = ConnectionState.CONNECTED
        websocket_service._ws = None
        websocket_service._recv_task = None

        await websocket_service._partial_cleanup()

        # State must remain CONNECTED — _partial_cleanup is resource cleanup, not state transition
        assert websocket_service.connection_state == ConnectionState.CONNECTED

    async def test_partial_cleanup_no_state_change_from_connecting(self, websocket_service: WebsocketService) -> None:
        """_partial_cleanup() does NOT change connection_state from CONNECTING either."""
        websocket_service._connection_state = ConnectionState.CONNECTING
        websocket_service._ws = None
        websocket_service._recv_task = None

        await websocket_service._partial_cleanup()

        assert websocket_service.connection_state == ConnectionState.CONNECTING
