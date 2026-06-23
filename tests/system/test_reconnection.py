"""System tests for WebSocket reconnection — verifies Hassette recovers from an HA restart."""

import asyncio
import subprocess

import pytest

from hassette.events import RawStateChangeEvent
from hassette.test_utils import wait_for

from .conftest import HA_CONTAINER_NAME, make_system_config, startup_context, toggle_and_capture, wait_for_ha_ready

# These tests restart HA mid-run to exercise reconnection. Give each its own event loop so
# residual tasks cannot bleed across tests on the shared session-scoped loop (see test_shutdown).
pytestmark = [pytest.mark.system_destructive, pytest.mark.asyncio(loop_scope="function")]

ENTITY = "light.kitchen_lights"


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

        assert websocket_service.is_ready()

        subprocess.run(["docker", "restart", HA_CONTAINER_NAME], check=True)

        await wait_for(
            lambda: not websocket_service.is_ready(),
            timeout=30.0,
            interval=0.5,
            desc="WebSocket disconnect detected after HA restart",
        )

        await asyncio.to_thread(wait_for_ha_ready)

        await wait_for(
            websocket_service.is_ready,
            timeout=60.0,
            interval=0.5,
            desc="WebSocket reconnected after HA restart",
        )

        received = await toggle_and_capture(bus, hassette.api, ENTITY, timeout=30.0)

        assert len(received) >= 1
        assert all(isinstance(e, RawStateChangeEvent) for e in received)


async def test_early_drop_retry_does_not_increment_restart_counter(ha_container: str, tmp_path) -> None:
    """Early-drop retry handles HA restart without consuming ServiceWatcher restart budget.

    This is the primary acceptance test for issue #629. After an HA restart causes
    the WebSocket to drop and reconnect, the ServiceWatcher restart counter must
    remain at zero — proving the early-drop retry loop in serve() handled recovery
    internally without escalating to handle_failed().

    Sequence:
    1. Start Hassette and confirm it is fully connected.
    2. Record the ServiceWatcher restart counter (should be 0).
    3. Restart the HA container.
    4. Wait for disconnect detection, then reconnect.
    5. Assert the restart counter is still 0 — zero budget consumed.
    6. Verify event delivery works (functional confirmation).
    """
    await asyncio.to_thread(wait_for_ha_ready)
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        websocket_service = hassette.websocket_service
        service_watcher = hassette._service_watcher  # pyright: ignore[reportPrivateUsage]
        bus = hassette._bus  # pyright: ignore[reportPrivateUsage]

        assert websocket_service.is_ready()
        assert service_watcher is not None

        ws_key = "WebsocketService:Service"
        budget_before = service_watcher._budgets.get(ws_key)  # pyright: ignore[reportPrivateUsage]
        assert budget_before is None or budget_before.current_attempts() == 0

        subprocess.run(["docker", "restart", HA_CONTAINER_NAME], check=True)

        await wait_for(
            lambda: not websocket_service.is_ready(),
            timeout=30.0,
            interval=0.5,
            desc="WebSocket disconnect detected after HA restart",
        )

        await asyncio.to_thread(wait_for_ha_ready)

        await wait_for(
            websocket_service.is_ready,
            timeout=60.0,
            interval=0.5,
            desc="WebSocket reconnected after HA restart",
        )

        budget_after = service_watcher._budgets.get(ws_key)  # pyright: ignore[reportPrivateUsage]
        restart_count = budget_after.current_attempts() if budget_after else 0
        assert restart_count == 0, (
            "ServiceWatcher restart counter should be 0 — early-drop retry should have handled "
            f"reconnection without escalating to handle_failed() (got {restart_count})"
        )

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

        await wait_for(
            lambda: not hassette.websocket_service.is_ready(),
            timeout=30.0,
            interval=0.5,
            desc="WebSocket disconnect detected after HA restart",
        )

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
