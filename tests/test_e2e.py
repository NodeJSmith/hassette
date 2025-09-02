import pytest

from hassette.core.core import Hassette
from hassette.models import states
from hassette.models.entities import SunEntity

pytestmark = pytest.mark.requires_ha


async def test_get_states_call(hassette_core: Hassette) -> None:
    """Test actual WebSocket calls against running HA instance."""
    inst = hassette_core.api

    # Give more time for real network calls

    # These will make real API calls to your test HA instance
    entities = await inst.get_states()
    assert entities, "Entities should not be empty."
    assert isinstance(entities, list), "Entities should be a list."


async def test_get_config_call(hassette_core: Hassette) -> None:
    """Test actual WebSocket calls against running HA instance."""
    inst = hassette_core.api

    # Give more time for real network calls

    config = await inst.get_config()
    assert config, "Config should not be empty."
    # Make assertions more flexible for different HA configurations
    assert isinstance(config, dict), "Config should be a dictionary"


async def test_get_services_call(hassette_core: Hassette) -> None:
    """Test actual WebSocket calls against running HA instance."""
    inst = hassette_core.api

    # Give more time for real network calls

    services = await inst.get_services()
    assert services, "Services should not be empty."
    assert "homeassistant" in services, "Should have homeassistant domain"


async def test_get_panels_call(hassette_core: Hassette) -> None:
    """Test actual WebSocket calls against running HA instance."""
    inst = hassette_core.api

    # Give more time for real network calls

    panels = await inst.get_panels()
    assert panels, "Panels should not be empty."
    assert isinstance(panels, dict), "Panels should be a dictionary"


async def test_get_state(hassette_core: Hassette) -> None:
    """Test actual WebSocket calls against running HA instance."""
    inst = hassette_core.api

    state = await inst.get_state_value("sun.sun")
    assert state, "State should not be empty."
    assert isinstance(state, str)


async def test_get_state_raw(hassette_core: Hassette) -> None:
    """Test actual WebSocket calls against running HA instance."""
    inst = hassette_core.api

    # Give more time for real network calls

    entity = await inst.get_state_raw("sun.sun")
    assert entity["entity_id"] == "sun.sun", "Entity ID should match"
    assert isinstance(entity, dict), "Entity should be a dictionary"


async def test_get_state_typed(hassette_core: Hassette) -> None:
    """Test actual WebSocket calls against running HA instance."""
    inst = hassette_core.api

    # Give more time for real network calls

    entity = await inst.get_state("sun.sun", states.SunState)
    assert isinstance(entity, states.SunState), "Entity should be of type SunState"
    assert entity.entity_id == "sun.sun", "Entity ID should match"


async def test_get_entity(hassette_core: Hassette) -> None:
    """Test actual WebSocket calls against running HA instance."""
    inst = hassette_core.api

    # Give more time for real network calls

    entity = await inst.get_entity("sun.sun", SunEntity)
    assert entity, "Entity should not be None"
    assert entity.entity_id == "sun.sun", "Entity ID should match"
    assert entity.domain == "sun", "Domain should be sun"
    assert isinstance(entity.state, states.SunState), "State should be of type SunState"


async def test_sync_call_from_async_raises_exception(hassette_core: Hassette) -> None:
    """Test actual WebSocket calls against running HA instance."""
    inst = hassette_core.api

    # Give more time for real network calls
    with pytest.raises(RuntimeError, match="This sync method was called from within an event loop"):
        inst.sync.get_config()


def test_sync_call_from_sync_works(hassette_core_sync: Hassette) -> None:
    """Test actual WebSocket calls against running HA instance."""

    # Give more time for real network calls
    config = hassette_core_sync.api.sync.get_config()

    assert config, "Config should not be empty."
    # Make assertions more flexible for different HA configurations
    assert isinstance(config, dict), "Config should be a dictionary"
