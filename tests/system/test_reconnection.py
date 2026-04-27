"""System tests for WebSocket reconnection — verifies Hassette recovers from an HA connection drop."""

import subprocess

import pytest

from hassette.events import RawStateChangeEvent
from hassette.test_utils import wait_for

from .conftest import HA_CONTAINER_NAME, make_system_config, startup_context, toggle_and_capture

pytestmark = [pytest.mark.system]

_ENTITY = "light.kitchen_lights"


async def test_websocket_reconnects_after_ha_restart(ha_container: str, tmp_path) -> None:
    """Hassette detects a WebSocket disconnect when HA is paused and reconnects with active subscriptions after unpause.

    Sequence:
    1. Start Hassette and confirm it is fully connected (WebSocket ready + subscriptions active).
    2. Pause the HA container — simulates a hard connection drop from the HA side.
    3. Wait until Hassette detects the disconnect (websocket_service.is_ready() becomes False).
    4. Unpause the HA container — HA resumes accepting connections.
    5. Wait until Hassette reconnects (websocket_service.is_ready() and _subscription_ids non-empty).
    6. Register a bus handler and toggle the light — verify a state-change event arrives within 30s of unpause.
    """
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        websocket_service = hassette.websocket_service
        bus = hassette._bus  # pyright: ignore[reportPrivateUsage]

        # Step 1: confirm connected on entry (startup_context guarantees this via _session_ready)
        assert websocket_service.is_ready()
        assert bool(websocket_service._subscription_ids)  # pyright: ignore[reportPrivateUsage]

        # Step 2: pause the HA container
        subprocess.run(["docker", "pause", HA_CONTAINER_NAME], check=True)

        try:
            # Step 3: wait until Hassette detects the disconnect
            await wait_for(
                lambda: not websocket_service.is_ready(),
                timeout=15.0,
                interval=0.5,
                desc="WebSocket disconnect detected after HA pause",
            )

            # Step 4: unpause the HA container
            subprocess.run(["docker", "unpause", HA_CONTAINER_NAME], check=True)

            # Step 5: wait until Hassette reconnects with active subscriptions
            await wait_for(
                lambda: websocket_service.is_ready() and bool(websocket_service._subscription_ids),  # pyright: ignore[reportPrivateUsage]
                timeout=30.0,
                interval=0.5,
                desc="WebSocket reconnected with active subscriptions after HA unpause",
            )

            # Step 6: verify events flow through the reconnected WebSocket
            received = await toggle_and_capture(bus, hassette.api, _ENTITY, timeout=30.0)

        except BaseException:
            # If any step fails, always attempt to unpause so the container is not left stuck
            subprocess.run(["docker", "unpause", HA_CONTAINER_NAME], check=False)
            raise

        assert len(received) >= 1
        assert all(isinstance(e, RawStateChangeEvent) for e in received)


async def test_state_proxy_refreshes_after_reconnect(ha_container: str, tmp_path) -> None:
    """State proxy recovers and reflects valid entity state after an HA connection drop and reconnect.

    Sequence:
    1. Start Hassette and read the initial state of light.kitchen_lights from the state proxy.
    2. Pause the HA container.
    3. Wait for the state proxy to lose readiness (WebSocket disconnected).
    4. Unpause the HA container.
    5. Wait until the state proxy is ready again and its states dict is non-empty.
    6. Verify that light.kitchen_lights is present and has a valid state string.
    """
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        state_proxy = hassette.state_proxy

        # Step 1: read initial state
        initial = state_proxy.get_state(_ENTITY)
        assert initial is not None, f"Entity {_ENTITY!r} not in state proxy at startup"
        assert isinstance(initial["state"], str)

        # Step 2: pause the HA container
        subprocess.run(["docker", "pause", HA_CONTAINER_NAME], check=True)

        try:
            # Step 3: wait for disconnect detection (state proxy becomes not ready)
            await wait_for(
                lambda: not hassette.websocket_service.is_ready(),
                timeout=15.0,
                interval=0.5,
                desc="WebSocket disconnect detected after HA pause",
            )

            # Step 4: unpause the HA container
            subprocess.run(["docker", "unpause", HA_CONTAINER_NAME], check=True)

            # Step 5: wait until the state proxy is ready and states are populated
            await wait_for(
                lambda: state_proxy.is_ready() and len(state_proxy.states) > 0,
                timeout=30.0,
                interval=0.5,
                desc="state proxy ready with non-empty states after reconnect",
            )

        except BaseException:
            subprocess.run(["docker", "unpause", HA_CONTAINER_NAME], check=False)
            raise

        # Step 6: verify kitchen_lights is present with a valid state
        recovered = state_proxy.get_state(_ENTITY)
        assert recovered is not None, f"Entity {_ENTITY!r} missing from state proxy after reconnect"
        assert isinstance(recovered["state"], str)
        assert recovered["state"] in ("on", "off", "unavailable"), (
            f"Unexpected state value for {_ENTITY!r} after reconnect: {recovered['state']!r}"
        )
