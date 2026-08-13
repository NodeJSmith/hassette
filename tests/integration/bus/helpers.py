"""Shared helpers for bus integration tests."""

import asyncio

from hassette.test_utils.harness import HassetteHarness
from hassette.test_utils.helpers import create_state_change_event, make_state_dict

ENTITY = "sensor.overlap"
"""Shared entity id for execution-mode overlap tests (test_execution_modes*.py)."""

# Yielding to the event loop this many times lets a chain of already-scheduled callbacks
# (stream → serve → dispatch → guard → child-task spawn) all run without waiting on wall-clock
# time. Used where there is no completion signal to await on.
EVENT_LOOP_YIELDS = 10


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
    await harness.hassette.send_event(event)
    await harness.bus_service.await_dispatch_idle()


async def pump_event_loop() -> None:
    """Yield control to the event loop enough times for scheduled callbacks to drain."""
    for _ in range(EVENT_LOOP_YIELDS):
        await asyncio.sleep(0)


async def fire(harness: HassetteHarness, old: str, new: str) -> None:
    """Send one state-change event on ENTITY without waiting for dispatch to drain.

    A blocking handler keeps dispatch non-idle, so ``await_dispatch_idle`` cannot be used here.
    The event travels the stream → serve → dispatch → guard → child-task path, so callers wait on
    an explicit started-signal (``wait_for``) rather than this function before asserting.
    """
    event = create_state_change_event(entity_id=ENTITY, old_value=old, new_value=new)
    await harness.send_event(event)
    await pump_event_loop()
