"""Unit tests for WebsocketService connection state machine.

Tests for the ConnectionState enum (DISCONNECTED, CONNECTING, CONNECTED, AUTH_FAILED),
set_connection_state() validation, and the transitions serve() and cleanup() write.
"""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

import hassette.core.websocket_reconnect as reconnect_module
from hassette.core.websocket_service import WebsocketService
from hassette.exceptions import InvalidAuthError, RetryableConnectionClosedError
from hassette.testing import wait_for
from hassette.testing.config import TEST_WS_URL
from hassette.types.enums import ConnectionState

from .conftest import cleanup_disconnected, stub_refused_attempts

ALLOWED_TRANSITIONS = {
    (ConnectionState.DISCONNECTED, ConnectionState.CONNECTING),
    (ConnectionState.CONNECTING, ConnectionState.CONNECTED),
    (ConnectionState.CONNECTING, ConnectionState.AUTH_FAILED),
    (ConnectionState.CONNECTING, ConnectionState.DISCONNECTED),
    (ConnectionState.CONNECTED, ConnectionState.CONNECTING),
    (ConnectionState.CONNECTED, ConnectionState.DISCONNECTED),
    (ConnectionState.AUTH_FAILED, ConnectionState.DISCONNECTED),
}
"""The transition table ratified in design/specs/131-ha-restart-reconnect (D10). AUTH_FAILED has
no edge back to CONNECTING: leaving it takes a process restart."""

ALL_STATE_PAIRS = [(old, new) for old in ConnectionState for new in ConnectionState if old != new]


class TestInitialState:
    async def test_initial_state_disconnected(self, websocket_service: WebsocketService) -> None:
        """New WebsocketService has connection_state == DISCONNECTED."""
        assert websocket_service.connection_state == ConnectionState.DISCONNECTED


class TestIsConnectedPropertyMirrorsState:
    async def test_is_connected_true_only_for_connected_state(self, websocket_service: WebsocketService) -> None:
        """is_connected returns True only when connection_state == CONNECTED."""
        # DISCONNECTED → not connected
        websocket_service._connection_state = ConnectionState.DISCONNECTED
        assert websocket_service.is_connected is False

        # CONNECTING → not connected
        websocket_service._connection_state = ConnectionState.CONNECTING
        assert websocket_service.is_connected is False

        # CONNECTED → connected
        websocket_service._connection_state = ConnectionState.CONNECTED
        assert websocket_service.is_connected is True


class TestWaitConnected:
    async def test_returns_true_when_already_connected(self, websocket_service: WebsocketService) -> None:
        websocket_service._connection_state = ConnectionState.CONNECTING
        websocket_service.set_connection_state(ConnectionState.CONNECTED)
        websocket_service._connected_event.set()

        assert await websocket_service.wait_connected(timeout=0.01) is True

    async def test_returns_false_when_timeout_expires(self, websocket_service: WebsocketService) -> None:
        assert await websocket_service.wait_connected(timeout=0.01) is False


class TestConnectedGeneration:
    async def test_returns_generation_only_for_externally_ready_connection(
        self, websocket_service: WebsocketService
    ) -> None:
        assert websocket_service.get_connected_generation() is None

        websocket_service._connection_state = ConnectionState.CONNECTING
        websocket_service._connected_generation = 3
        assert websocket_service.get_connected_generation() is None

        websocket_service._connection_state = ConnectionState.CONNECTED
        assert websocket_service.get_connected_generation() is None

        websocket_service._connected_event.set()
        assert websocket_service.get_connected_generation() == 3

    async def test_wait_connected_generation_returns_active_generation(
        self, websocket_service: WebsocketService
    ) -> None:
        websocket_service._connection_state = ConnectionState.CONNECTED
        websocket_service._connected_generation = 7
        websocket_service._connected_event.set()

        assert await websocket_service.wait_connected_generation(timeout=0.01) == 7

    async def test_wait_connected_generation_times_out(self, websocket_service: WebsocketService) -> None:
        assert await websocket_service.wait_connected_generation(timeout=0.01) is None


class TestTransitionTable:
    @pytest.mark.parametrize(("old", "new"), ALL_STATE_PAIRS, ids=lambda state: state.value)
    async def test_every_pair_matches_the_ratified_table(
        self, websocket_service: WebsocketService, old: ConnectionState, new: ConnectionState
    ) -> None:
        """Every pair applies; only pairs outside the ratified table warn."""
        websocket_service._connection_state = old
        websocket_service.logger = Mock()

        websocket_service.set_connection_state(new)

        assert websocket_service.connection_state == new
        assert websocket_service.logger.warning.called is ((old, new) not in ALLOWED_TRANSITIONS)


class TestConnectionStateLogging:
    """Entering and leaving CONNECTED is reported at INFO, so it survives the default log level.

    The quickstart points a new user at the "Connected to Home Assistant" line to confirm their
    URL and token work, which makes these messages behavior rather than incidental logging.
    Logger is mocked rather than captured via caplog, matching the convention in
    test_service_watcher_coverage.py.
    """

    async def test_first_connection_logs_connected_with_url(self, websocket_service: WebsocketService) -> None:
        websocket_service._connection_state = ConnectionState.CONNECTING
        websocket_service.logger = Mock()

        websocket_service.set_connection_state(ConnectionState.CONNECTED)

        websocket_service.logger.info.assert_called_once_with(
            "Connected to Home Assistant at %s", websocket_service.url
        )

    async def test_reconnect_transition_leaves_the_recovery_line_to_the_outage_log(
        self, websocket_service: WebsocketService
    ) -> None:
        """A reconnect is reported once, by OutageLog.record_connected, with the outage's duration."""
        websocket_service._connection_state = ConnectionState.CONNECTING
        websocket_service.set_connection_state(ConnectionState.CONNECTED)
        websocket_service.set_connection_state(ConnectionState.CONNECTING)

        websocket_service.logger = Mock()
        websocket_service.set_connection_state(ConnectionState.CONNECTED)

        websocket_service.logger.info.assert_not_called()

    async def test_leaving_connected_logs_nothing_at_info(self, websocket_service: WebsocketService) -> None:
        """OutageLog reports the drop, at a level that depends on whether it was a flap (D11)."""
        websocket_service._connection_state = ConnectionState.CONNECTING
        websocket_service.set_connection_state(ConnectionState.CONNECTED)

        websocket_service.logger = Mock()
        websocket_service.set_connection_state(ConnectionState.CONNECTING)

        websocket_service.logger.info.assert_not_called()

    async def test_failed_first_attempt_logs_nothing_at_info(self, websocket_service: WebsocketService) -> None:
        """CONNECTING → DISCONNECTED without ever connecting has no connection to report losing."""
        websocket_service._connection_state = ConnectionState.CONNECTING
        websocket_service.logger = Mock()

        websocket_service.set_connection_state(ConnectionState.DISCONNECTED)

        websocket_service.logger.info.assert_not_called()


class TestStartupUrlLogging:
    async def test_initialize_logs_both_resolved_urls(self, websocket_service: WebsocketService) -> None:
        """Both URLs are reported before any connection attempt, so a wrong base_url path is visible on failure."""
        websocket_service.hassette.rest_url = "http://supervisor/core/api/"
        websocket_service.logger = Mock()

        await websocket_service.on_initialize()

        websocket_service.logger.info.assert_called_once_with(
            "Home Assistant URLs: REST %s, WebSocket %s", "http://supervisor/core/api/", TEST_WS_URL
        )


class TestInvalidTransitions:
    async def test_invalid_transition_warns_and_applies(self, websocket_service: WebsocketService) -> None:
        """DISCONNECTED → CONNECTED logs a WARNING and the new state is still applied."""
        websocket_service._connection_state = ConnectionState.DISCONNECTED
        websocket_service.logger = Mock()

        websocket_service.set_connection_state(ConnectionState.CONNECTED)

        websocket_service.logger.warning.assert_called_once()
        assert websocket_service.connection_state == ConnectionState.CONNECTED

    async def test_self_transition_is_a_silent_noop(self, websocket_service: WebsocketService) -> None:
        """CONNECTED → CONNECTED is not an invalid transition: nothing is logged and the state stays."""
        websocket_service._connection_state = ConnectionState.CONNECTED
        websocket_service.logger = Mock()

        websocket_service.set_connection_state(ConnectionState.CONNECTED)

        websocket_service.logger.warning.assert_not_called()
        assert websocket_service.connection_state == ConnectionState.CONNECTED


@pytest.fixture
def instant_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reconnect_module, "FAST_BACKOFF_CAP_SECONDS", 0.0)


@pytest.mark.usefixtures("instant_backoff")
class TestServeTransitions:
    async def test_drop_and_reconnect_sequence(self, websocket_service: WebsocketService) -> None:
        """CONNECTING → CONNECTED → CONNECTING → CONNECTED across a drop, inside one serve() call."""
        websocket_service.hassette.send_event = AsyncMock()
        states = record_states(websocket_service)
        attempts = 0

        async def fake_run_connection(_session) -> None:
            nonlocal attempts
            attempts += 1
            websocket_service.set_connection_state(ConnectionState.CONNECTED)
            if attempts == 1:
                raise RetryableConnectionClosedError("peer gone")

        websocket_service.run_connection = fake_run_connection  # pyright: ignore[reportAttributeAccessIssue]

        await websocket_service.serve()

        assert states == [
            ConnectionState.CONNECTING,
            ConnectionState.CONNECTED,
            ConnectionState.CONNECTING,
            ConnectionState.CONNECTED,
        ]

    async def test_failed_attempts_stay_in_connecting_without_transitions(
        self, websocket_service: WebsocketService
    ) -> None:
        """An outage of many failed attempts produces exactly one transition: the initial CONNECTING."""
        states = record_states(websocket_service)
        run_connection = stub_refused_attempts(websocket_service, failures=9)

        await websocket_service.serve()

        assert run_connection.await_count == 10
        assert states == [ConnectionState.CONNECTING]

    async def test_auth_rejection_parks_in_auth_failed(
        self, websocket_service: WebsocketService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A token rejected on every attempt, retries included, parks: AUTH_FAILED, and serve() keeps running."""
        monkeypatch.setattr(reconnect_module, "AUTH_RETRY_SECONDS", 0.0)

        async def fake_run_connection(_session) -> None:
            raise InvalidAuthError("bad token")

        websocket_service.run_connection = fake_run_connection  # pyright: ignore[reportAttributeAccessIssue]
        websocket_service._emit_readiness_event = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

        task = asyncio.create_task(websocket_service.serve())
        try:
            await wait_for(
                lambda: websocket_service.connection_state == ConnectionState.AUTH_FAILED,
                timeout=5.0,
                desc="parked",
            )
            assert not task.done()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def record_states(websocket_service: WebsocketService) -> list[ConnectionState]:
    """Record the state after every set_connection_state() call that changed it."""
    states: list[ConnectionState] = []
    original_set = websocket_service.set_connection_state

    def capture_set(new: ConnectionState) -> None:
        before = websocket_service.connection_state
        original_set(new)
        if websocket_service.connection_state != before:
            states.append(websocket_service.connection_state)

    websocket_service.set_connection_state = capture_set  # pyright: ignore[reportAttributeAccessIssue]
    return states


class TestCleanShutdownDisconnects:
    async def test_clean_shutdown_disconnects(self, websocket_service: WebsocketService) -> None:
        """cleanup() sets DISCONNECTED at the start (clean shutdown path)."""
        # First put service into CONNECTED state
        websocket_service._connection_state = ConnectionState.CONNECTED

        await cleanup_disconnected(websocket_service)

        assert websocket_service.connection_state == ConnectionState.DISCONNECTED


class TestPartialCleanupNoStateChange:
    async def test_partial_cleanup_no_state_change(self, websocket_service: WebsocketService) -> None:
        """partial_cleanup() does NOT change connection_state."""
        # Put into CONNECTED state
        websocket_service._connection_state = ConnectionState.CONNECTED
        websocket_service._ws = None
        websocket_service._recv_task = None

        await websocket_service.partial_cleanup()

        # State must remain CONNECTED — partial_cleanup is resource cleanup, not state transition
        assert websocket_service.connection_state == ConnectionState.CONNECTED

    async def test_partial_cleanup_no_state_change_from_connecting(self, websocket_service: WebsocketService) -> None:
        """partial_cleanup() does NOT change connection_state from CONNECTING either."""
        websocket_service._connection_state = ConnectionState.CONNECTING
        websocket_service._ws = None
        websocket_service._recv_task = None

        await websocket_service.partial_cleanup()

        assert websocket_service.connection_state == ConnectionState.CONNECTING
