"""Integration tests for Bus.wait_for() using real Bus wiring via HassetteHarness.

Unlike unit tests for wait_for, these exercise the primitive end-to-end: real listener
registration, real event dispatch through the Bus, and (for the composition test) a real
RecordingApi call_service invocation to prove the documented arm-before-fire pattern works
with the actual dispatch pipeline, not a mocked one.
"""

import asyncio

from hassette.testing import create_state_change_event, wait_for
from hassette.types import Topic
from tests.support.factories import make_recording_api

from .conftest import ASYNC_SAFETY_TIMEOUT

ENTITY_ID = "light.kitchen"
STATE_CHANGED_TOPIC = str(Topic.HASS_EVENT_STATE_CHANGED)


def _entity_topic(entity_id: str) -> str:
    return f"{STATE_CHANGED_TOPIC}.{entity_id}"


async def test_wait_for_resolves_on_real_bus_dispatch(bus_harness) -> None:
    """A real state_changed event dispatched through the Bus resolves a pending wait_for."""
    _, hassette, bus = bus_harness

    wait_task = asyncio.create_task(bus.wait_for(_entity_topic(ENTITY_ID), timeout=ASYNC_SAFETY_TIMEOUT))
    await wait_for(lambda: len(bus._wait_for_futures) == 1, desc="wait_for listener registered")

    event = create_state_change_event(entity_id=ENTITY_ID, old_value="off", new_value="on")
    await hassette.send_event(event)

    result = await asyncio.wait_for(wait_task, timeout=ASYNC_SAFETY_TIMEOUT)

    assert result.payload.data.entity_id == ENTITY_ID
    assert result.payload.data.new_state is not None
    assert result.payload.data.new_state["state"] == "on"


async def test_wait_for_composes_with_call_service_arm_before_fire(bus_harness) -> None:
    """The documented arm-before-fire pattern: create_task(wait_for), call a service, then dispatch.

    This is the composition pattern that motivated the primitive: arm the wait before
    triggering the side effect that is expected to eventually cause the matching event,
    so no event can be missed between triggering and awaiting.
    """
    _, hassette, bus = bus_harness

    def matches_turned_on(event) -> bool:
        new_state = event.payload.data.new_state
        return new_state is not None and new_state["state"] == "on"

    # Arm the wait before triggering the service call that is expected to cause it.
    wait_task = asyncio.create_task(
        bus.wait_for(_entity_topic(ENTITY_ID), where=matches_turned_on, timeout=ASYNC_SAFETY_TIMEOUT)
    )
    await wait_for(lambda: len(bus._wait_for_futures) == 1, desc="wait_for listener registered")

    api = make_recording_api()
    await api.turn_on(ENTITY_ID)
    api.assert_called("turn_on", entity_id=ENTITY_ID)

    # Simulate Home Assistant reporting the resulting state change.
    event = create_state_change_event(entity_id=ENTITY_ID, old_value="off", new_value="on")
    await hassette.send_event(event)

    result = await asyncio.wait_for(wait_task, timeout=ASYNC_SAFETY_TIMEOUT)

    assert result.payload.data.entity_id == ENTITY_ID
    assert result.payload.data.new_state is not None
    assert result.payload.data.new_state["state"] == "on"


async def test_wait_for_where_clause_filters_real_dispatch(bus_harness) -> None:
    """A where predicate rejects non-matching real events and resolves only on a match."""
    harness, hassette, bus = bus_harness

    def matches_turned_on(event) -> bool:
        new_state = event.payload.data.new_state
        return new_state is not None and new_state["state"] == "on"

    wait_task = asyncio.create_task(
        bus.wait_for(_entity_topic(ENTITY_ID), where=matches_turned_on, timeout=ASYNC_SAFETY_TIMEOUT)
    )
    await wait_for(lambda: len(bus._wait_for_futures) == 1, desc="wait_for listener registered")

    non_matching = create_state_change_event(entity_id=ENTITY_ID, old_value="off", new_value="unavailable")
    await hassette.send_event(non_matching)

    # Wait for the dispatch pipeline to fully drain before asserting it did not resolve.
    await harness.bus_service.await_dispatch_idle()
    assert not wait_task.done(), "wait_for resolved on a non-matching event"

    matching = create_state_change_event(entity_id=ENTITY_ID, old_value="unavailable", new_value="on")
    await hassette.send_event(matching)

    result = await asyncio.wait_for(wait_task, timeout=ASYNC_SAFETY_TIMEOUT)
    assert result.payload.data.new_state is not None
    assert result.payload.data.new_state["state"] == "on"


async def test_wait_for_concurrent_waits_resolve_independently(bus_harness) -> None:
    """Two concurrent wait_for calls on the same topic resolve independently by predicate."""
    _, hassette, bus = bus_harness

    def matches_on(event) -> bool:
        new_state = event.payload.data.new_state
        return new_state is not None and new_state["state"] == "on"

    def matches_off(event) -> bool:
        new_state = event.payload.data.new_state
        return new_state is not None and new_state["state"] == "off"

    on_task = asyncio.create_task(
        bus.wait_for(_entity_topic(ENTITY_ID), where=matches_on, timeout=ASYNC_SAFETY_TIMEOUT, name="wait_on")
    )
    off_task = asyncio.create_task(
        bus.wait_for(_entity_topic(ENTITY_ID), where=matches_off, timeout=ASYNC_SAFETY_TIMEOUT, name="wait_off")
    )
    await wait_for(lambda: len(bus._wait_for_futures) == 2, desc="both wait_for listeners registered")

    off_event = create_state_change_event(entity_id=ENTITY_ID, old_value="unavailable", new_value="off")
    await hassette.send_event(off_event)

    off_result = await asyncio.wait_for(off_task, timeout=ASYNC_SAFETY_TIMEOUT)
    assert off_result.payload.data.new_state is not None
    assert off_result.payload.data.new_state["state"] == "off"
    assert not on_task.done(), "wait_for(matches_on) resolved on an 'off' event"

    on_event = create_state_change_event(entity_id=ENTITY_ID, old_value="off", new_value="on")
    await hassette.send_event(on_event)

    on_result = await asyncio.wait_for(on_task, timeout=ASYNC_SAFETY_TIMEOUT)
    assert on_result.payload.data.new_state is not None
    assert on_result.payload.data.new_state["state"] == "on"
