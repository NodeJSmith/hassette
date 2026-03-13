"""Startup smoke tests — run against a live Home Assistant container.

These tests verify that Hassette connects, creates a session, and surfaces
entities from the HA demo integration. They require a running HA container
(managed by the ``ha_container`` fixture in conftest.py).

Run with:
    pytest -m smoke -v
"""

import asyncio
import logging

import pytest

from hassette.bus import Bus
from hassette.events import RawStateChangeEvent
from tests.smoke.conftest import make_smoke_config, startup_context

pytestmark = [pytest.mark.smoke, pytest.mark.filterwarnings("default::DeprecationWarning")]


async def test_startup_completes(ha_container, tmp_path):
    """Hassette reaches the running state and records a positive session ID."""
    config = make_smoke_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        assert hassette._session_id is not None
        assert hassette._session_id > 0


async def test_session_created_in_db(ha_container, tmp_path):
    """A row exists in the sessions table with status='running' for the active session."""
    config = make_smoke_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        async with hassette.database_service.db.execute(
            "SELECT id, status FROM sessions WHERE id = ?", (hassette.session_id,)
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None
        assert row[1] == "running"


async def test_demo_entities_visible(ha_container, tmp_path):
    """Entities from the HA demo integration are present in the state list."""
    config = make_smoke_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        states = await hassette.api.get_states()
        entity_ids = {s.entity_id for s in states}
        assert "light.kitchen_lights" in entity_ids
        assert "binary_sensor.movement_backyard" in entity_ids


async def test_bus_handler_fires_on_state_change(ha_container, tmp_path):
    """A bus handler registered for a light entity fires after toggling that light."""
    config = make_smoke_config(ha_container, tmp_path)
    received: list[object] = []

    async def capture_event(event: RawStateChangeEvent) -> None:
        received.append(event)

    async with startup_context(config) as hassette:
        bus = hassette.add_child(Bus)
        bus.on_state_change("light.kitchen_lights", handler=capture_event)
        await hassette.api.call_service("light", "toggle", {"entity_id": "light.kitchen_lights"})
        await asyncio.sleep(1.5)

    assert len(received) >= 1, f"Expected state_changed event, got {received}"


async def test_no_sentinel_records_dropped(ha_container, tmp_path, caplog):
    """No sentinel/unregistered invocation records are dropped during startup."""
    config = make_smoke_config(ha_container, tmp_path)
    with caplog.at_level(logging.WARNING, logger="hassette.CommandExecutor"):
        async with startup_context(config):
            await asyncio.sleep(2.0)

    dropped = [r for r in caplog.records if "Dropping" in r.message and "invocation record" in r.message]
    assert dropped == [], f"Sentinel records dropped during startup: {[r.message for r in dropped]}"
