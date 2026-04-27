"""System tests for the event bus — real HA events through a running Hassette instance."""

import asyncio

import pytest

from hassette.events import RawStateChangeEvent
from hassette.test_utils import wait_for

from .conftest import make_system_config, startup_context, toggle_and_capture

pytestmark = [pytest.mark.system]

_ENTITY = "light.kitchen_lights"
_DOMAIN = "light"


async def test_state_change_handler_fires(ha_container: str, tmp_path):
    """A state-change handler registered via bus.on_state_change receives at least one event when the entity toggles."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        bus = hassette._bus  # pyright: ignore[reportPrivateUsage]
        received = await toggle_and_capture(bus, hassette.api, _ENTITY)
        assert len(received) >= 1
        assert all(isinstance(e, RawStateChangeEvent) for e in received)


async def test_attribute_change_handler_fires(ha_container: str, tmp_path):
    """An attribute-change handler fires when the brightness attribute is present in a state change."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        bus = hassette._bus  # pyright: ignore[reportPrivateUsage]
        api = hassette.api

        received: list[RawStateChangeEvent] = []

        async def _capture(event: RawStateChangeEvent) -> None:
            received.append(event)

        # Set a known starting state BEFORE registering the handler
        await api.call_service(_DOMAIN, "turn_on", {"entity_id": _ENTITY, "brightness": 50})
        await asyncio.sleep(1.0)

        sub = bus.on_attribute_change(_ENTITY, "brightness", handler=_capture)

        await wait_for(
            lambda: sub.listener.db_id is not None,
            timeout=10.0,
            desc="attribute listener DB registration",
        )

        # Change brightness to a distinctly different value — guaranteed attribute change
        await api.call_service(_DOMAIN, "turn_on", {"entity_id": _ENTITY, "brightness": 200})

        await wait_for(
            lambda: len(received) >= 1,
            timeout=15.0,
            desc="attribute_changed event for brightness on kitchen_lights",
        )

        assert len(received) >= 1


async def test_glob_pattern_matching(ha_container: str, tmp_path):
    """A glob pattern subscription (light.*) receives events for light.kitchen_lights."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        bus = hassette._bus  # pyright: ignore[reportPrivateUsage]
        api = hassette.api

        received: list[RawStateChangeEvent] = []

        async def _capture(event: RawStateChangeEvent) -> None:
            received.append(event)

        bus.on_state_change("light.*", handler=_capture)

        await api.call_service(_DOMAIN, "toggle", {"entity_id": _ENTITY})
        await wait_for(
            lambda: len(received) >= 1,
            timeout=15.0,
            desc="state_changed event via glob pattern light.*",
        )

        assert len(received) >= 1
        assert all(e.payload.entity_id.startswith("light.") for e in received)


async def test_changed_to_predicate(ha_container: str, tmp_path):
    """A changed_to='on' handler fires only when the light turns on, not when it turns off."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        bus = hassette._bus  # pyright: ignore[reportPrivateUsage]
        api = hassette.api

        received: list[RawStateChangeEvent] = []

        async def _capture(event: RawStateChangeEvent) -> None:
            received.append(event)

        bus.on_state_change(_ENTITY, changed_to="on", handler=_capture)

        # Ensure a known starting state — light is off
        await api.call_service(_DOMAIN, "turn_off", {"entity_id": _ENTITY})
        await asyncio.sleep(1.0)

        # Turn on — handler should fire
        await api.call_service(_DOMAIN, "turn_on", {"entity_id": _ENTITY})
        await wait_for(
            lambda: len(received) >= 1,
            timeout=15.0,
            desc="changed_to='on' handler fires on turn_on",
        )
        assert len(received) >= 1
        count_after_on = len(received)

        # Turn off — handler must NOT fire again
        await api.call_service(_DOMAIN, "turn_off", {"entity_id": _ENTITY})
        await asyncio.sleep(2.0)
        assert len(received) == count_after_on, (
            f"Handler fired on turn_off — expected {count_after_on} events, got {len(received)}"
        )


async def test_debounce(ha_container: str, tmp_path):
    """A debounced handler fires at most once after 3 rapid toggles followed by a 2s wait."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        bus = hassette._bus  # pyright: ignore[reportPrivateUsage]
        api = hassette.api

        received: list[RawStateChangeEvent] = []

        async def _capture(event: RawStateChangeEvent) -> None:
            received.append(event)

        bus.on_state_change(_ENTITY, handler=_capture, debounce=1.0)

        # Toggle 3 times rapidly — debounce window resets each time
        for _ in range(3):
            await api.call_service(_DOMAIN, "toggle", {"entity_id": _ENTITY})
            await asyncio.sleep(0.05)

        # Wait for the debounced delivery to arrive
        await wait_for(
            lambda: len(received) >= 1,
            timeout=10.0,
            desc="debounced handler fired at least once",
        )

        # Wait past debounce window to confirm no additional events
        await asyncio.sleep(2.5)

        assert len(received) == 1, f"Expected exactly 1 debounced event, got {len(received)}"


async def test_throttle(ha_container: str, tmp_path):
    """A throttled handler fires at most once regardless of multiple toggles within the window."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        bus = hassette._bus  # pyright: ignore[reportPrivateUsage]
        api = hassette.api

        received: list[RawStateChangeEvent] = []

        async def _capture(event: RawStateChangeEvent) -> None:
            received.append(event)

        bus.on_state_change(_ENTITY, handler=_capture, throttle=2.0)

        # Toggle 3 times with 0.3s gaps — all within the 2s throttle window
        for _ in range(3):
            await api.call_service(_DOMAIN, "toggle", {"entity_id": _ENTITY})
            await asyncio.sleep(0.3)

        # Wait for the leading-edge delivery (throttle fires on the first event)
        await wait_for(
            lambda: len(received) >= 1,
            timeout=10.0,
            desc="throttle leading-edge event delivered",
        )

        # Wait past the toggle burst — no additional events should arrive within the window
        await asyncio.sleep(1.0)

        assert len(received) == 1, f"Expected exactly 1 throttled event, got {len(received)}"


async def test_once_handler(ha_container: str, tmp_path):
    """A once=True handler fires exactly once even when the entity toggles multiple times."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        bus = hassette._bus  # pyright: ignore[reportPrivateUsage]
        api = hassette.api

        received: list[RawStateChangeEvent] = []

        async def _capture(event: RawStateChangeEvent) -> None:
            received.append(event)

        sub = bus.on_state_change(_ENTITY, handler=_capture, once=True)

        # once=True registration awaits DB write before adding the route —
        # wait for db_id to confirm the route is active before toggling
        await wait_for(
            lambda: sub.listener.db_id is not None,
            timeout=10.0,
            desc="once=True listener DB registration",
        )

        # First toggle — handler fires
        await api.call_service(_DOMAIN, "toggle", {"entity_id": _ENTITY})
        await wait_for(
            lambda: len(received) >= 1,
            timeout=15.0,
            desc="once=True handler fires on first toggle",
        )

        # Brief pause to let any spurious second delivery occur before the second toggle
        await asyncio.sleep(0.3)

        # Second toggle — handler must not fire again (already removed after first event)
        await api.call_service(_DOMAIN, "toggle", {"entity_id": _ENTITY})
        await asyncio.sleep(2.0)

        assert len(received) == 1, f"once=True handler should fire exactly once, got {len(received)}"


async def test_multiple_handlers_same_entity(ha_container: str, tmp_path):
    """Two handlers registered on the same entity both receive events when the entity changes."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        bus = hassette._bus  # pyright: ignore[reportPrivateUsage]
        api = hassette.api

        received_a: list[RawStateChangeEvent] = []
        received_b: list[RawStateChangeEvent] = []

        async def _capture_a(event: RawStateChangeEvent) -> None:
            received_a.append(event)

        async def _capture_b(event: RawStateChangeEvent) -> None:
            received_b.append(event)

        bus.on_state_change(_ENTITY, handler=_capture_a, name="handler_a")
        bus.on_state_change(_ENTITY, handler=_capture_b, name="handler_b")

        await api.call_service(_DOMAIN, "toggle", {"entity_id": _ENTITY})

        await wait_for(
            lambda: len(received_a) >= 1 and len(received_b) >= 1,
            timeout=15.0,
            desc="both handlers receive a state_changed event",
        )

        assert len(received_a) >= 1
        assert len(received_b) >= 1
