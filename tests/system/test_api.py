"""System tests for the API — real HA interactions through a running Hassette instance."""

import asyncio
from typing import Any

import pytest

import hassette.utils.date_utils as date_utils
from hassette.events import Event
from hassette.test_utils import wait_for

from .conftest import make_system_config, startup_context

pytestmark = [pytest.mark.system]

_ENTITY = "light.kitchen_lights"
_DOMAIN = "light"


async def test_get_state_single_entity(ha_container: str, tmp_path) -> None:
    """get_state returns a state object with a matching entity_id and a string state value."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        state = await hassette.api.get_state(_ENTITY)
        assert state.entity_id == _ENTITY
        assert isinstance(state.value, str)
        assert state.value in ("on", "off")


async def test_set_state_roundtrip(ha_container: str, tmp_path) -> None:
    """set_state persists and get_state reads back the new value for both 'on' and 'off'."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        entity = "input_boolean.test"

        await hassette.api.set_state(entity, "on", {})
        result_on = await hassette.api.get_state(entity)
        assert result_on.value == "on"

        await hassette.api.set_state(entity, "off", {})
        result_off = await hassette.api.get_state(entity)
        assert result_off.value == "off"


async def test_fire_event_received_by_bus(ha_container: str, tmp_path) -> None:
    """fire_event causes a matching event to arrive on the bus with the expected data."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        bus = hassette._bus  # pyright: ignore[reportPrivateUsage]
        captured: list[Event[Any]] = []

        async def _capture(event: Event[Any]) -> None:
            captured.append(event)

        # Custom HA events are dispatched on topic "hass.event.<event_type>"
        bus.on(topic="hass.event.custom_test_event", handler=_capture)

        await hassette.api.fire_event("custom_test_event", {"key": "value"})

        await wait_for(
            lambda: len(captured) >= 1,
            timeout=10.0,
            desc="custom_test_event received on bus",
        )

        assert len(captured) >= 1
        # For unrecognised event types the data is a plain dict on payload.data
        event_data = captured[0].payload.data  # pyright: ignore[reportAttributeAccessIssue]
        assert event_data.get("key") == "value"


async def test_render_template(ha_container: str, tmp_path) -> None:
    """render_template returns the string state of the entity."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        result = await hassette.api.render_template(f"{{{{ states('{_ENTITY}') }}}}")
        assert isinstance(result, str)
        assert result in ("on", "off")


async def test_get_config(ha_container: str, tmp_path) -> None:
    """get_config returns a dict containing 'components' and 'unit_system' keys."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        ha_config = await hassette.api.get_config()
        assert isinstance(ha_config, dict)
        assert "components" in ha_config
        assert "unit_system" in ha_config


async def test_get_history(ha_container: str, tmp_path) -> None:
    """get_history returns a non-empty list after toggling the entity."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        # Record a timestamp before the toggle so the history window includes it
        start = date_utils.now().subtract(seconds=120)

        await hassette.api.call_service(_DOMAIN, "toggle", {"entity_id": _ENTITY})

        deadline = asyncio.get_running_loop().time() + 15.0
        history: list = []  # pyright: ignore[reportMissingTypeArgument]
        while not history and asyncio.get_running_loop().time() < deadline:
            history = await hassette.api.get_history(_ENTITY, start_time=start)
            if not history:
                await asyncio.sleep(0.5)
        assert isinstance(history, list)
        assert len(history) > 0
