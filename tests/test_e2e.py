import asyncio

import pytest

from hassette.core.core import Hassette
from hassette.models import states
from hassette.models.entities import LightEntity

pytestmark = pytest.mark.requires_ha


async def test_get_states_call(hassette_core: Hassette) -> None:
    """Test actual WebSocket calls against running HA instance."""
    inst = hassette_core.api

    # These will make real API calls to your test HA instance
    entities = await inst.get_states()
    await asyncio.sleep(0.1)
    assert entities, "Entities should not be empty."
    assert isinstance(entities, list), "Entities should be a list."


async def test_get_config_call(hassette_core: Hassette) -> None:
    """Test actual WebSocket calls against running HA instance."""
    inst = hassette_core.api

    config = await inst.get_config()
    await asyncio.sleep(0.1)
    assert config, "Config should not be empty."
    # Make assertions more flexible for different HA configurations
    assert isinstance(config, dict), "Config should be a dictionary"


async def test_get_services_call(hassette_core: Hassette) -> None:
    """Test actual WebSocket calls against running HA instance."""
    inst = hassette_core.api

    services = await inst.get_services()
    await asyncio.sleep(0.1)
    assert services, "Services should not be empty."
    assert "homeassistant" in services, "Should have homeassistant domain"


async def test_get_panels_call(hassette_core: Hassette) -> None:
    """Test actual WebSocket calls against running HA instance."""
    inst = hassette_core.api

    panels = await inst.get_panels()
    await asyncio.sleep(0.1)
    assert panels, "Panels should not be empty."
    assert isinstance(panels, dict), "Panels should be a dictionary"


async def test_get_state(hassette_core: Hassette) -> None:
    """Test actual WebSocket calls against running HA instance."""
    inst = hassette_core.api

    state = await inst.get_state_value("sun.sun")
    await asyncio.sleep(0.1)
    assert state, "State should not be empty."
    assert isinstance(state, str)


async def test_get_state_raw(hassette_core: Hassette) -> None:
    """Test actual WebSocket calls against running HA instance."""
    inst = hassette_core.api

    entity = await inst.get_state_raw("sun.sun")
    await asyncio.sleep(0.1)
    assert entity["entity_id"] == "sun.sun", "Entity ID should match"
    assert isinstance(entity, dict), "Entity should be a dictionary"


async def test_get_state_typed(hassette_core: Hassette) -> None:
    """Test actual WebSocket calls against running HA instance."""
    inst = hassette_core.api

    entity = await inst.get_state("sun.sun", states.SunState)
    await asyncio.sleep(0.1)
    assert isinstance(entity, states.SunState), "Entity should be of type SunState"
    assert entity.entity_id == "sun.sun", "Entity ID should match"


async def test_get_entity(hassette_core: Hassette) -> None:
    """Test actual WebSocket calls against running HA instance."""
    inst = hassette_core.api

    entity = await inst.get_entity("light.bed_light", LightEntity)
    await asyncio.sleep(0.1)
    assert entity, "Entity should not be None"
    assert entity.entity_id == "light.bed_light", "Entity ID should match"
    assert entity.domain == "light", "Domain should be light"
    assert isinstance(entity.state, states.LightState), "State should be of type LightState"


async def test_sync_call_from_async_raises_exception(hassette_core: Hassette) -> None:
    """Test actual WebSocket calls against running HA instance."""
    inst = hassette_core.api

    with pytest.raises(RuntimeError, match="This sync method was called from within an event loop"):
        inst.sync.get_config()


def test_sync_call_from_sync_works(hassette_core_sync: Hassette) -> None:
    """Test actual WebSocket calls against running HA instance."""

    config = hassette_core_sync.api.sync.get_config()

    assert config, "Config should not be empty."
    # Make assertions more flexible for different HA configurations
    assert isinstance(config, dict), "Config should be a dictionary"
