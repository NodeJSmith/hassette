"""Connection lifecycle rows: one per ConnectionState transition, each with the detail its call site knows.

Spec 152 D4 (a row per transition) and D6 (a direct call, last in set_connection_state, with a detail built at the
call site).
"""

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, Mock

import pytest

import hassette.core.websocket_reconnect as reconnect_module
import hassette.core.websocket_service as service_module
from hassette.core.telemetry.lifecycle_rows import ConnectionDetails
from hassette.core.websocket_service import WebsocketService
from hassette.exceptions import InvalidAuthError, WebsocketClosedError
from hassette.testing import wait_for
from hassette.types.enums import ConnectionState

from .conftest import HA_CONFIG, run_core_running_gate


@dataclass(frozen=True)
class Row:
    old: ConnectionState
    new: ConnectionState
    detail: ConnectionDetails | None


@pytest.fixture
def rows(monkeypatch: pytest.MonkeyPatch) -> list[Row]:
    """Capture every connection row the service writes, in order."""
    captured: list[Row] = []

    def record(_hassette: object, old: ConnectionState, new: ConnectionState, detail: ConnectionDetails | None) -> None:
        captured.append(Row(old, new, detail))

    monkeypatch.setattr(service_module, "record_connection_change", record)
    return captured


class TestSetConnectionState:
    async def test_each_transition_writes_one_row_and_same_state_writes_none(
        self, websocket_service: WebsocketService, rows: list[Row]
    ) -> None:
        websocket_service.set_connection_state(ConnectionState.CONNECTING)
        websocket_service.set_connection_state(ConnectionState.CONNECTING)
        websocket_service.set_connection_state(ConnectionState.CONNECTED)

        assert rows == [
            Row(ConnectionState.DISCONNECTED, ConnectionState.CONNECTING, None),
            Row(ConnectionState.CONNECTING, ConnectionState.CONNECTED, None),
        ]

    async def test_row_is_written_after_the_transition_is_applied(
        self, websocket_service: WebsocketService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The writer runs last, so it sees the new state and the cleared generation."""
        seen: list[tuple[ConnectionState, int | None]] = []
        monkeypatch.setattr(
            service_module,
            "record_connection_change",
            lambda *_: seen.append((websocket_service.connection_state, websocket_service._connected_generation)),
        )
        websocket_service._connection_state = ConnectionState.CONNECTED
        websocket_service._connected_generation = 3

        websocket_service.set_connection_state(ConnectionState.DISCONNECTED)

        assert seen == [(ConnectionState.DISCONNECTED, None)]

    async def test_an_unwired_writer_never_breaks_the_transition(self, websocket_service: WebsocketService) -> None:
        """With no session manager wired, the real ``record_connection_change`` drops the row and returns."""
        websocket_service.hassette.session_manager = None  # pyright: ignore[reportAttributeAccessIssue]

        websocket_service.set_connection_state(ConnectionState.CONNECTING)

        assert websocket_service.connection_state == ConnectionState.CONNECTING


@pytest.fixture
def instant_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reconnect_module, "FAST_BACKOFF_CAP_SECONDS", 0.0)


class TestCallSiteDetails:
    @pytest.mark.usefixtures("instant_backoff")
    async def test_reconnect_after_a_drop_carries_the_cause(
        self, websocket_service: WebsocketService, rows: list[Row]
    ) -> None:
        websocket_service.hassette.send_event = AsyncMock()
        attempts = 0

        async def fake_run_connection(_session: object) -> None:
            nonlocal attempts
            attempts += 1
            websocket_service.set_connection_state(ConnectionState.CONNECTED)
            if attempts == 1:
                raise WebsocketClosedError("peer gone")

        websocket_service.run_connection = fake_run_connection  # pyright: ignore[reportAttributeAccessIssue]

        await websocket_service.serve()

        reconnect = rows[2]
        assert (reconnect.old, reconnect.new) == (ConnectionState.CONNECTED, ConnectionState.CONNECTING)
        assert reconnect.detail is not None
        assert reconnect.detail.cause
        assert rows[0].detail is None  # the session-start CONNECTING has no failure behind it

    async def test_park_carries_the_rejection_cause(
        self, websocket_service: WebsocketService, rows: list[Row], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(reconnect_module, "AUTH_RETRY_SECONDS", 0.0)

        async def fake_run_connection(_session: object) -> None:
            raise InvalidAuthError("bad token")

        websocket_service.run_connection = fake_run_connection  # pyright: ignore[reportAttributeAccessIssue]
        websocket_service._emit_readiness_event = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

        task = asyncio.create_task(websocket_service.serve())
        try:
            await wait_for(
                lambda: websocket_service.connection_state == ConnectionState.AUTH_FAILED, timeout=5.0, desc="parked"
            )
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        assert rows[-1] == Row(
            ConnectionState.CONNECTING,
            ConnectionState.AUTH_FAILED,
            ConnectionDetails(cause=reconnect_module.AUTH_REJECTED_REASON),
        )

    async def test_core_wait_carries_the_first_core_state_once(
        self, websocket_service: WebsocketService, rows: list[Row], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(service_module, "CORE_RUNNING_RECHECK_SECONDS", 0.01)
        replies = iter(["NOT_RUNNING", "STARTING", "RUNNING"])

        async def read_config(**_: object) -> dict[str, object]:
            return {**HA_CONFIG, "state": next(replies)}

        websocket_service.send_and_wait = AsyncMock(side_effect=read_config)  # pyright: ignore[reportAttributeAccessIssue]
        websocket_service.hassette.send_event = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
        websocket_service._connection_state = ConnectionState.CONNECTING

        await run_core_running_gate(websocket_service)

        assert rows == [
            Row(
                ConnectionState.CONNECTING,
                ConnectionState.WAITING_FOR_CORE,
                ConnectionDetails(core_state="NOT_RUNNING"),
            )
        ]

    async def test_recv_task_death_carries_the_close_code(
        self, websocket_service: WebsocketService, rows: list[Row]
    ) -> None:
        task = asyncio.create_task(asyncio.sleep(0))
        await task
        websocket_service._recv_task = task
        websocket_service._ws = Mock(close_code=1006)
        websocket_service._connection_state = ConnectionState.CONNECTED

        websocket_service._handle_recv_task_done(task)

        assert rows == [
            Row(ConnectionState.CONNECTED, ConnectionState.DISCONNECTED, ConnectionDetails(close_code=1006))
        ]
