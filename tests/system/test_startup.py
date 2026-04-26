"""System tests for Hassette startup lifecycle."""

import pytest

from .conftest import make_system_config, startup_context

pytestmark = [pytest.mark.system]


async def test_startup_completes(ha_container: str, tmp_path):
    """Hassette reaches a running state and creates a valid session ID."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        assert hassette.session_id > 0


async def test_demo_entities_visible(ha_container: str, tmp_path):
    """HA API returns real entities including the demo fixture entities."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        states = await hassette.api.get_states()
        entity_ids = {s.entity_id for s in states}
        assert "light.kitchen_lights" in entity_ids
        assert "binary_sensor.movement_backyard" in entity_ids


async def test_session_persisted_as_running(ha_container: str, tmp_path):
    """A session row with status='running' exists in the DB for the current session_id."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        session_id = hassette.session_id
        async with hassette.database_service.db.execute(
            "SELECT status FROM sessions WHERE id = ?", (session_id,)
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "running"
