"""Unit tests for WebsocketService readiness event emission.

Lifecycle readiness never tracks the HA connection; the ready reason carries its status. These
tests pin that serve() emits a status event each time that reason changes, and not per retry (D11).
"""

import asyncio
from unittest.mock import AsyncMock

import pytest

import hassette.core.websocket_reconnect as reconnect_module
import hassette.core.websocket_service as service_module
from hassette.core.websocket_reconnect import (
    AUTH_REJECTED_REASON,
    CONNECTED_REASON,
    CORE_NOT_RUNNING_REASON,
    NOT_CONNECTED_REASON,
    OutageLog,
)
from hassette.core.websocket_service import WebsocketService
from hassette.exceptions import RetryableConnectionClosedError
from hassette.testing import EventCapture
from hassette.testing._ws_mocks import run_connect_sequence
from hassette.types import Topic
from hassette.types.enums import ConnectionState
from tests.support.websocket_mocks import stub_connect_sequence

from .conftest import stub_refused_attempts


def status_reasons(event_capture: EventCapture) -> list[str | None]:
    return [event.payload.data.ready_phase for event in event_capture.by_topic(Topic.HASSETTE_EVENT_SERVICE_STATUS)]


@pytest.fixture
async def initialized_service(websocket_service: WebsocketService, event_capture: EventCapture) -> WebsocketService:
    """The service after ``on_initialize()``, with ``event_capture`` installed to record its status events."""
    event_capture.install(websocket_service.hassette)
    await websocket_service.on_initialize()
    return websocket_service


@pytest.fixture
def instant_fast_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove the Fast-disposition backoff wait so a multi-attempt serve() runs in microseconds."""
    monkeypatch.setattr(reconnect_module, "FAST_BACKOFF_CAP_SECONDS", 0.0)


class TestWebsocketReadinessEvents:
    """The HA connection's status is the ready reason: one status event per change, never a readiness flip (R1)."""

    @pytest.mark.usefixtures("instant_fast_backoff")
    async def test_drop_of_established_connection_reports_not_connected_and_stays_ready(
        self, initialized_service: WebsocketService, event_capture: EventCapture
    ) -> None:
        """Losing an established connection changes the reason to NOT_CONNECTED_REASON; ready stays True."""
        attempts = 0

        async def fake_run_connection(_session) -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                await run_connect_sequence(initialized_service, stub_connect_sequence(initialized_service))
                raise RetryableConnectionClosedError("peer gone")

        initialized_service.run_connection = fake_run_connection  # pyright: ignore[reportAttributeAccessIssue]

        await initialized_service.serve()

        events = event_capture.by_topic(Topic.HASSETTE_EVENT_SERVICE_STATUS)
        assert [e.payload.data.ready_phase for e in events] == [CONNECTED_REASON, NOT_CONNECTED_REASON]
        assert all(e.payload.data.ready for e in events)
        assert initialized_service.is_ready() is True

    @pytest.mark.usefixtures("instant_fast_backoff")
    async def test_failed_attempts_before_any_connection_emit_one_not_connected_event(
        self, initialized_service: WebsocketService, event_capture: EventCapture
    ) -> None:
        """A first-start outage shows NOT_CONNECTED_REASON, and repeated failures with one cause emit one event."""
        stub_refused_attempts(initialized_service, failures=4)

        await initialized_service.serve()

        assert status_reasons(event_capture) == [NOT_CONNECTED_REASON]
        assert initialized_service.is_ready() is True

    async def test_connect_emits_one_status_event_with_the_connected_reason(
        self, initialized_service: WebsocketService, event_capture: EventCapture
    ) -> None:
        """mark_connected reports CONNECTED_REASON through a service_status event, without touching readiness."""
        await run_connect_sequence(initialized_service, stub_connect_sequence(initialized_service))

        assert status_reasons(event_capture) == [CONNECTED_REASON]
        assert initialized_service.is_ready() is True

    async def test_running_gate_reports_the_core_state_and_stays_ready(
        self, initialized_service: WebsocketService, event_capture: EventCapture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """While HA's core is not RUNNING the reason names the state, once, and the service stays ready."""
        monkeypatch.setattr(service_module, "CORE_RUNNING_RECHECK_SECONDS", 0.01)
        initialized_service._outage_log = OutageLog(initialized_service.logger, initialized_service.url)
        initialized_service.send_and_wait = AsyncMock(  # pyright: ignore[reportAttributeAccessIssue]
            side_effect=[{"state": "NOT_RUNNING"}, {"state": "NOT_RUNNING"}, {"state": "RUNNING"}]
        )
        recv_task = asyncio.create_task(asyncio.sleep(10))

        await initialized_service.wait_for_core_running(recv_task)
        recv_task.cancel()

        assert status_reasons(event_capture) == [CORE_NOT_RUNNING_REASON.format("NOT_RUNNING")]
        assert initialized_service.is_ready() is True

    async def test_park_reports_the_auth_rejection_and_stays_ready(
        self, initialized_service: WebsocketService, event_capture: EventCapture
    ) -> None:
        task = asyncio.create_task(initialized_service.park())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        assert status_reasons(event_capture) == [AUTH_REJECTED_REASON]
        assert initialized_service.connection_state is ConnectionState.AUTH_FAILED
        assert initialized_service.is_ready() is True

    async def test_nothing_is_reported_after_shutdown_begins(
        self, initialized_service: WebsocketService, event_capture: EventCapture
    ) -> None:
        """Shutdown's own reason wins: a connection status reported once shutdown_event is set is dropped."""
        initialized_service.shutdown_event.set()

        await initialized_service.report_connection_status(NOT_CONNECTED_REASON)

        assert status_reasons(event_capture) == []
        assert initialized_service._ready_reason != NOT_CONNECTED_REASON

    async def test_reentrant_disconnect_during_connected_dispatch_emits_disconnected_event(
        self,
        websocket_service: WebsocketService,
    ) -> None:
        """A disconnect triggered during connected handlers still emits the public disconnect signal."""
        topics: list[Topic] = []

        async def reentrant_send(event) -> None:
            topics.append(event.topic)
            if event.topic == Topic.HASSETTE_EVENT_WEBSOCKET_CONNECTED:
                await websocket_service.send_connection_lost_event()

        spawned_coros = stub_connect_sequence(websocket_service)
        websocket_service.hassette.send_event = reentrant_send
        websocket_service._connection_state = ConnectionState.CONNECTING

        await run_connect_sequence(websocket_service, spawned_coros)

        assert topics == [
            Topic.HASSETTE_EVENT_SERVICE_STATUS,
            Topic.HASSETTE_EVENT_WEBSOCKET_CONNECTED,
            Topic.HASSETTE_EVENT_WEBSOCKET_DISCONNECTED,
        ]

    async def test_connected_event_failure_does_not_revoke_external_readiness(
        self,
        websocket_service: WebsocketService,
    ) -> None:
        """Connected-event delivery is observational, not part of WebSocket capability."""

        async def fail_connected_event(event) -> None:
            if event.topic == Topic.HASSETTE_EVENT_WEBSOCKET_CONNECTED:
                raise RuntimeError("event stream closed")

        spawned_coros = stub_connect_sequence(websocket_service)
        websocket_service.hassette.send_event = fail_connected_event
        websocket_service._connection_state = ConnectionState.CONNECTING

        await run_connect_sequence(websocket_service, spawned_coros)

        assert websocket_service.is_connected is True
        assert await websocket_service.wait_connected(timeout=0) is True
        assert websocket_service.get_connected_generation() == 1


class TestHasEverConnectedLatch:
    """has_ever_connected latch starts False, flips True on CONNECTED, stays True after disconnect."""

    def test_has_ever_connected_starts_false(self, websocket_service: WebsocketService) -> None:
        """has_ever_connected is False before any connection transition."""
        assert websocket_service.has_ever_connected is False

    def test_has_ever_connected_becomes_true_after_connected_transition(
        self,
        websocket_service: WebsocketService,
    ) -> None:
        """has_ever_connected flips True when set_connection_state transitions to CONNECTED."""
        websocket_service.set_connection_state(ConnectionState.CONNECTING)
        assert websocket_service.has_ever_connected is False  # not yet

        websocket_service.set_connection_state(ConnectionState.CONNECTED)
        assert websocket_service.has_ever_connected is True

    def test_has_ever_connected_stays_true_after_disconnect(
        self,
        websocket_service: WebsocketService,
    ) -> None:
        """has_ever_connected remains True after a subsequent disconnect (one-way latch)."""
        websocket_service.set_connection_state(ConnectionState.CONNECTING)
        websocket_service.set_connection_state(ConnectionState.CONNECTED)
        assert websocket_service.has_ever_connected is True

        websocket_service.set_connection_state(ConnectionState.DISCONNECTED)
        assert websocket_service.has_ever_connected is True  # latch does not revert
