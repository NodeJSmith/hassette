"""WebsocketService keeps its own copy of Home Assistant's location and time zone (``ha_core_config``)."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.core.ha_core_config import HaCoreConfig
from hassette.core.websocket_service import WebsocketService
from hassette.exceptions import ResponseTimeoutError
from hassette.testing._ws_mocks import make_task_bucket_spawn_stub
from hassette.types.enums import ConnectionState

HA_CONFIG: dict[str, Any] = {
    "state": "RUNNING",
    "latitude": 52.37,
    "longitude": 4.89,
    "elevation": 12,
    "time_zone": "Europe/Amsterdam",
    "unit_system": {"length": "km"},
}

MOVED_CONFIG: dict[str, Any] = {**HA_CONFIG, "latitude": 40.71, "longitude": -74.0, "time_zone": "America/New_York"}

CORE_CONFIG_UPDATED_ENVELOPE: dict[str, Any] = {
    "type": "event",
    "id": 1,
    "event": {
        "event_type": "core_config_updated",
        "data": {},
        "origin": "LOCAL",
        "time_fired": "2026-10-25T12:00:00+00:00",
        "context": {"id": "ctx", "parent_id": None, "user_id": None},
    },
}


def stub_get_config(service: WebsocketService, *responses: dict[str, Any] | Exception) -> AsyncMock:
    send_and_wait = AsyncMock(side_effect=list(responses))
    service.send_and_wait = send_and_wait  # pyright: ignore[reportAttributeAccessIssue]
    return send_and_wait


async def run_core_running_gate(service: WebsocketService) -> None:
    recv_task = asyncio.create_task(asyncio.sleep(10))
    try:
        await service.wait_for_core_running(recv_task)
    finally:
        recv_task.cancel()
        await asyncio.gather(recv_task, return_exceptions=True)


def expected(config: dict[str, Any]) -> HaCoreConfig:
    return HaCoreConfig(
        latitude=config["latitude"],
        longitude=config["longitude"],
        elevation=config["elevation"],
        time_zone=config["time_zone"],
    )


async def test_read_before_load_is_none(websocket_service: WebsocketService) -> None:
    assert websocket_service.ha_core_config is None


async def test_running_gate_loads_config_before_connected(websocket_service: WebsocketService) -> None:
    stub_get_config(websocket_service, HA_CONFIG)

    await run_core_running_gate(websocket_service)

    assert websocket_service.connection_state is not ConnectionState.CONNECTED
    assert websocket_service.ha_core_config == expected(HA_CONFIG)


async def test_zero_zero_is_a_real_location(websocket_service: WebsocketService) -> None:
    origin = {**HA_CONFIG, "latitude": 0, "longitude": 0, "elevation": 0}
    stub_get_config(websocket_service, origin)

    await run_core_running_gate(websocket_service)

    assert websocket_service.ha_core_config == expected(origin)


async def test_reconnect_replaces_config(websocket_service: WebsocketService) -> None:
    stub_get_config(websocket_service, HA_CONFIG, MOVED_CONFIG)

    await run_core_running_gate(websocket_service)
    await run_core_running_gate(websocket_service)

    assert websocket_service.ha_core_config == expected(MOVED_CONFIG)


async def test_malformed_response_warns_and_keeps_previous_value(
    websocket_service: WebsocketService, caplog: pytest.LogCaptureFixture
) -> None:
    stub_get_config(websocket_service, HA_CONFIG, {"state": "RUNNING", "latitude": "north"})

    await run_core_running_gate(websocket_service)
    await run_core_running_gate(websocket_service)

    assert websocket_service.ha_core_config == expected(HA_CONFIG)
    assert any(r.levelname == "WARNING" and "get_config" in r.getMessage() for r in caplog.records)


async def test_started_event_rereads_config_dropped_while_connecting(websocket_service: WebsocketService) -> None:
    # A core_config_updated during STARTING is dropped before CONNECTED; ending the wait must still re-read.
    replies = iter([{**HA_CONFIG, "state": "STARTING"}, MOVED_CONFIG])

    async def get_config(**_: Any) -> dict[str, Any]:
        reply = next(replies)
        if reply["state"] == "STARTING":
            # homeassistant_started lands after the STARTING reply, as dispatch_hass_event would set it.
            websocket_service._core_started_event.set()  # pyright: ignore[reportPrivateUsage]
        return reply

    send_and_wait = AsyncMock(side_effect=get_config)
    websocket_service.send_and_wait = send_and_wait  # pyright: ignore[reportAttributeAccessIssue]
    websocket_service.report_connection_status = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

    await run_core_running_gate(websocket_service)

    assert send_and_wait.await_count == 2
    assert websocket_service.ha_core_config == expected(MOVED_CONFIG)


async def test_malformed_first_response_does_not_block_startup(websocket_service: WebsocketService) -> None:
    stub_get_config(websocket_service, {"state": "RUNNING"})

    await run_core_running_gate(websocket_service)

    assert websocket_service.ha_core_config is None


class TestCoreConfigUpdated:
    """A ``core_config_updated`` event re-reads ``get_config`` in a framework task and still reaches the bus."""

    @pytest.fixture
    def connected_service(self, websocket_service: WebsocketService) -> WebsocketService:
        websocket_service.set_connection_state(ConnectionState.CONNECTING)
        websocket_service.set_connection_state(ConnectionState.CONNECTED)
        websocket_service.hassette.send_event = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
        websocket_service.ha_core_config = expected(HA_CONFIG)
        return websocket_service

    async def test_event_replaces_config_with_a_fresh_read(self, connected_service: WebsocketService) -> None:
        send_and_wait = stub_get_config(connected_service, MOVED_CONFIG)
        spawned, spawn = make_task_bucket_spawn_stub()
        connected_service.task_bucket = MagicMock(spawn=spawn)  # pyright: ignore[reportAttributeAccessIssue]

        await connected_service.dispatch_hass_event(CORE_CONFIG_UPDATED_ENVELOPE)  # pyright: ignore[reportArgumentType]
        assert len(spawned) == 1
        await spawned[0]

        send_and_wait.assert_awaited_once_with(type="get_config")
        assert connected_service.ha_core_config == expected(MOVED_CONFIG)
        connected_service.hassette.send_event.assert_awaited_once()  # pyright: ignore[reportAttributeAccessIssue]

    async def test_failed_reread_warns_and_keeps_previous_value(
        self, connected_service: WebsocketService, caplog: pytest.LogCaptureFixture
    ) -> None:
        stub_get_config(connected_service, ResponseTimeoutError("no reply"))

        await connected_service.refresh_ha_core_config()

        assert connected_service.ha_core_config == expected(HA_CONFIG)
        assert any(r.levelname == "WARNING" and "no reply" in r.getMessage() for r in caplog.records)

    async def test_other_events_do_not_reread(self, connected_service: WebsocketService) -> None:
        connected_service.task_bucket = MagicMock()  # pyright: ignore[reportAttributeAccessIssue]
        envelope = {
            **CORE_CONFIG_UPDATED_ENVELOPE,
            "event": {**CORE_CONFIG_UPDATED_ENVELOPE["event"], "event_type": "x"},
        }

        await connected_service.dispatch_hass_event(envelope)  # pyright: ignore[reportArgumentType]

        connected_service.task_bucket.spawn.assert_not_called()
