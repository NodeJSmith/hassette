"""System tests for WebSocket reconnection — verifies Hassette recovers from an HA restart."""

import asyncio
import subprocess

import pytest

import hassette.core.websocket_reconnect as reconnect_module
from hassette.core.websocket_service import WebsocketService
from hassette.events import RawStateChangeEvent
from hassette.testing import wait_for

from .conftest import HA_CONTAINER_NAME, make_system_config, startup_context, toggle_and_capture, wait_for_ha_ready

# These tests restart HA mid-run to exercise reconnection. Give each its own event loop so
# residual tasks cannot bleed across tests on the shared session-scoped loop (see test_shutdown).
pytestmark = [pytest.mark.system_destructive, pytest.mark.asyncio(loop_scope="function")]

ENTITY = "light.kitchen_lights"
STABLE_WINDOW_FOR_TEST_SECONDS = 5.0
"""Stands in for the 2-minute D8 reset window, so a connection held this long counts as stable."""


async def wait_for_disconnect(websocket_service: WebsocketService) -> None:
    """Wait until the service notices that the HA restart dropped its connection."""
    await wait_for(
        lambda: not websocket_service.is_connected,
        timeout=30.0,
        interval=0.5,
        desc="WebSocket disconnect detected after HA restart",
    )


async def test_websocket_reconnects_after_ha_restart(ha_container: str, tmp_path) -> None:
    """Hassette detects a WebSocket disconnect when HA restarts and reconnects with active subscriptions.

    Sequence:
    1. Start Hassette and confirm it is fully connected.
    2. Restart the HA container — immediately closes the TCP connection.
    3. Wait until Hassette detects the disconnect.
    4. Wait until HA comes back and Hassette reconnects with active subscriptions.
    5. Register a bus handler and toggle the light — verify event delivery works.
    """
    await asyncio.to_thread(wait_for_ha_ready)
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        websocket_service = hassette.websocket_service
        bus = hassette._bus  # pyright: ignore[reportPrivateUsage]

        assert websocket_service.is_connected

        subprocess.run(["docker", "restart", HA_CONTAINER_NAME], check=True)

        await wait_for_disconnect(websocket_service)

        await asyncio.to_thread(wait_for_ha_ready)

        await wait_for(
            lambda: websocket_service.is_connected,
            timeout=60.0,
            interval=0.5,
            desc="WebSocket reconnected after HA restart",
        )

        received = await toggle_and_capture(bus, hassette.api, ENTITY, timeout=30.0)

        assert len(received) >= 1
        assert all(isinstance(e, RawStateChangeEvent) for e in received)


async def test_restart_after_stable_connection_recovers_in_the_same_serve_task(
    ha_container: str, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An HA restart that ends a long-lived connection is recovered in place, never via ServiceWatcher.

    Acceptance test for design/specs/131-ha-restart-reconnect: a drop of a stable connection,
    and the refused connections while HA restarts, are retried inside serve() and never reach
    ServiceWatcher. The D8 reset window is shrunk so the connection counts as stable without
    the test waiting 2 minutes.

    Sequence:
    1. Start Hassette, confirm it is connected, and hold the connection past the reset window.
    2. Restart the HA container.
    3. Wait for the disconnect, then the reconnect.
    4. Assert the same serve() task is still running and ServiceWatcher never restarted the service.
    5. Verify event delivery works (functional confirmation).
    """
    monkeypatch.setattr(reconnect_module, "STABLE_CONNECTION_SECONDS", STABLE_WINDOW_FOR_TEST_SECONDS)
    await asyncio.to_thread(wait_for_ha_ready)
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        websocket_service = hassette.websocket_service
        service_watcher = hassette._service_watcher  # pyright: ignore[reportPrivateUsage]
        bus = hassette._bus  # pyright: ignore[reportPrivateUsage]

        assert websocket_service.is_connected
        assert service_watcher is not None
        serve_task = websocket_service._serve_task  # pyright: ignore[reportPrivateUsage]
        assert serve_task is not None

        await asyncio.sleep(STABLE_WINDOW_FOR_TEST_SECONDS + 1)

        subprocess.run(["docker", "restart", HA_CONTAINER_NAME], check=True)

        await wait_for_disconnect(websocket_service)

        await asyncio.to_thread(wait_for_ha_ready)

        await wait_for(
            lambda: websocket_service.is_connected,
            timeout=60.0,
            interval=0.5,
            desc="WebSocket reconnected after HA restart",
        )

        assert websocket_service._serve_task is serve_task  # pyright: ignore[reportPrivateUsage]
        assert not serve_task.done()
        budget = service_watcher._budgets.get("WebsocketService:Service")  # pyright: ignore[reportPrivateUsage]
        restart_count = budget.current_attempts() if budget else 0
        assert restart_count == 0, f"ServiceWatcher restarted WebsocketService {restart_count} time(s)"

        received = await toggle_and_capture(bus, hassette.api, ENTITY, timeout=30.0)
        assert len(received) >= 1


async def test_state_proxy_refreshes_after_reconnect(ha_container: str, tmp_path) -> None:
    """State proxy recovers and reflects valid entity state after an HA restart.

    Sequence:
    1. Start Hassette and confirm the state proxy has the entity.
    2. Restart the HA container.
    3. Wait for disconnect then reconnect.
    4. Wait until the state proxy is ready with populated states.
    5. Verify that light.kitchen_lights has a valid state.
    """
    await asyncio.to_thread(wait_for_ha_ready)
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        state_proxy = hassette.state_proxy

        await wait_for(
            lambda: state_proxy.is_ready() and len(state_proxy.states) > 0,
            timeout=15.0,
            desc="state proxy ready with populated states",
        )

        initial = state_proxy.get_state(ENTITY)
        assert initial is not None, f"Entity {ENTITY!r} not in state proxy at startup"

        subprocess.run(["docker", "restart", HA_CONTAINER_NAME], check=True)

        await wait_for_disconnect(hassette.websocket_service)

        await asyncio.to_thread(wait_for_ha_ready)

        def _entity_available() -> bool:
            try:
                return state_proxy.get_state(ENTITY) is not None
            except Exception:
                return False

        await wait_for(
            _entity_available,
            timeout=60.0,
            interval=0.5,
            desc=f"{ENTITY} available in state proxy after reconnect",
        )

        recovered = state_proxy.get_state(ENTITY)
        assert isinstance(recovered["state"], str)
        assert recovered["state"] in ("on", "off", "unavailable"), (
            f"Unexpected state value for {ENTITY!r} after reconnect: {recovered['state']!r}"
        )
