"""System tests for the state proxy — verifying cache population, live updates, and StateManager typed access."""

import typing

import pytest

from hassette.core.state_proxy import StateCacheFreshness
from hassette.testing import wait_for

from .conftest import make_system_config, startup_context

if typing.TYPE_CHECKING:
    from hassette.core.state_proxy import StateProxy

pytestmark = [pytest.mark.system]

ENTITY = "light.kitchen_lights"
DOMAIN = "light"


async def wait_for_fresh_state_proxy(state_proxy: "StateProxy", *, timeout: float = 15.0) -> None:
    """Wait until the proxy's cache is fresh and non-empty — the common precondition across this file's tests."""
    await wait_for(
        lambda: state_proxy.cache_freshness == StateCacheFreshness.FRESH and len(state_proxy.states) > 0,
        timeout=timeout,
        desc="state proxy fresh with populated states",
    )


async def test_initial_state_loaded(ha_container: str, tmp_path) -> None:
    """After startup the state proxy contains a non-empty states dict including kitchen_lights."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        state_proxy = hassette.state_proxy
        await wait_for_fresh_state_proxy(state_proxy)
        assert len(state_proxy.states) > 0
        assert state_proxy.get_state(ENTITY) is not None


async def test_state_change_propagates_to_proxy(ha_container: str, tmp_path) -> None:
    """Toggling an entity via the API causes the state proxy to reflect the new value."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        state_proxy = hassette.state_proxy
        await wait_for_fresh_state_proxy(state_proxy)

        # Read the original state BEFORE toggling so we can detect the change
        original = state_proxy.get_state(ENTITY)
        assert original is not None, f"Entity {ENTITY!r} not found in state proxy before toggle"
        original_value: str = original["state"]

        # Toggle the light
        await hassette.api.call_service(DOMAIN, "toggle", {"entity_id": ENTITY})

        # Wait until the proxy reflects a different state
        await wait_for(
            lambda: ((current := state_proxy.get_state(ENTITY)) is not None and current["state"] != original_value),
            timeout=15.0,
            desc=f"state proxy to reflect toggled state for {ENTITY}",
        )

        updated = state_proxy.get_state(ENTITY)
        assert updated is not None
        assert updated["state"] != original_value


async def test_state_manager_typed_access(ha_container: str, tmp_path) -> None:
    """StateManager.states.light['kitchen_lights'] returns a typed state with .value and .attributes."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        await wait_for_fresh_state_proxy(hassette.state_proxy)
        state = hassette.states.light["kitchen_lights"]
        assert isinstance(state.value, bool)
        # attributes is a Pydantic model but behaves like a dict-accessible object
        # Verify it has the attribute and it is not None
        assert state.attributes is not None


async def test_state_manager_domain_iteration(ha_container: str, tmp_path) -> None:
    """Iterating hassette.states.light yields (entity_id, state) tuples for each light entity."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        await wait_for_fresh_state_proxy(hassette.state_proxy)
        entities = list(hassette.states.light.items())
        assert len(entities) > 0
        for entity_id, state in entities:
            assert isinstance(entity_id, str)
            assert entity_id.startswith("light.")
            assert isinstance(state.value, bool)
