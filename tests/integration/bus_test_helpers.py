"""Shared helpers for bus integration tests."""

from hassette.test_utils.harness import HassetteHarness
from hassette.test_utils.helpers import create_state_change_event, make_state_dict


async def seed(harness: HassetteHarness, entity_id: str, state_value: str) -> None:
    """Seed state into the StateProxy."""
    await harness.seed_state(
        entity_id,
        make_state_dict(entity_id, state_value),
    )


async def send_state_change(
    harness: HassetteHarness,
    entity_id: str,
    old_value: str,
    new_value: str,
) -> None:
    """Send a state change event into the bus."""
    event = create_state_change_event(entity_id=entity_id, old_value=old_value, new_value=new_value)
    await harness.hassette.send_event(event.topic, event)
    await harness.bus_service.await_dispatch_idle()
