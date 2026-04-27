"""System tests for WebSocket reconnection — verifies Hassette recovers from an HA restart."""

import subprocess

import pytest

from hassette.events import RawStateChangeEvent
from hassette.test_utils import wait_for

from .conftest import HA_CONTAINER_NAME, make_system_config, startup_context, toggle_and_capture

pytestmark = [pytest.mark.system]

_ENTITY = "light.kitchen_lights"


async def test_websocket_reconnects_after_ha_restart(ha_container: str, tmp_path) -> None:
    """Hassette detects a WebSocket disconnect when HA restarts and reconnects with active subscriptions.

    Sequence:
    1. Start Hassette and confirm it is fully connected.
    2. Restart the HA container — immediately closes the TCP connection.
    3. Wait until Hassette detects the disconnect.
    4. Wait until HA comes back and Hassette reconnects with active subscriptions.
    5. Register a bus handler and toggle the light — verify event delivery works.
    """
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        websocket_service = hassette.websocket_service
        bus = hassette._bus  # pyright: ignore[reportPrivateUsage]

        assert websocket_service.is_ready()
        assert bool(websocket_service._subscription_ids)  # pyright: ignore[reportPrivateUsage]

        subprocess.run(["docker", "restart", HA_CONTAINER_NAME], check=True)

        await wait_for(
            lambda: not websocket_service.is_ready(),
            timeout=30.0,
            interval=0.5,
            desc="WebSocket disconnect detected after HA restart",
        )

        await wait_for(
            lambda: websocket_service.is_ready() and bool(websocket_service._subscription_ids),  # pyright: ignore[reportPrivateUsage]
            timeout=60.0,
            interval=0.5,
            desc="WebSocket reconnected with active subscriptions after HA restart",
        )

        received = await toggle_and_capture(bus, hassette.api, _ENTITY, timeout=30.0)

        assert len(received) >= 1
        assert all(isinstance(e, RawStateChangeEvent) for e in received)


async def test_state_proxy_refreshes_after_reconnect(ha_container: str, tmp_path) -> None:
    """State proxy recovers and reflects valid entity state after an HA restart.

    Sequence:
    1. Start Hassette and confirm the state proxy has the entity.
    2. Restart the HA container.
    3. Wait for disconnect then reconnect.
    4. Wait until the state proxy is ready with populated states.
    5. Verify that light.kitchen_lights has a valid state.
    """
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        state_proxy = hassette.state_proxy

        await wait_for(
            lambda: state_proxy.is_ready() and len(state_proxy.states) > 0,
            timeout=15.0,
            desc="state proxy ready with populated states",
        )

        initial = state_proxy.get_state(_ENTITY)
        assert initial is not None, f"Entity {_ENTITY!r} not in state proxy at startup"

        subprocess.run(["docker", "restart", HA_CONTAINER_NAME], check=True)

        await wait_for(
            lambda: not hassette.websocket_service.is_ready(),
            timeout=30.0,
            interval=0.5,
            desc="WebSocket disconnect detected after HA restart",
        )

        await wait_for(
            lambda: hassette.websocket_service.is_ready() and state_proxy.is_ready() and len(state_proxy.states) > 0,
            timeout=60.0,
            interval=0.5,
            desc="state proxy ready with non-empty states after reconnect",
        )

        recovered = state_proxy.get_state(_ENTITY)
        assert recovered is not None, f"Entity {_ENTITY!r} missing from state proxy after reconnect"
        assert isinstance(recovered["state"], str)
        assert recovered["state"] in ("on", "off", "unavailable"), (
            f"Unexpected state value for {_ENTITY!r} after reconnect: {recovered['state']!r}"
        )
