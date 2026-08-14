"""Integration tests for immediate-fire (immediate=True) on Bus.on_state_change / on_attribute_change.

Each test builds a fresh harness with bus + state_proxy to avoid cross-test pollution.
State is seeded into the StateProxy via harness.seed_state() before the listener is registered.
"""

import asyncio
from typing import TYPE_CHECKING

import pytest
from whenever import ZonedDateTime

from hassette.events import RawStateChangeEvent
from hassette.test_utils import make_state_dict, wait_for
from hassette.test_utils.harness import HassetteHarness
from hassette.test_utils.helpers import create_state_change_event, settle

from .helpers import make_collector, seed

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.bus import Bus

IMMEDIATE_FIRE_TIMEOUT = 2.0  # safety ceiling when awaiting an immediate-fire handler invocation


async def test_immediate_fires_when_state_matches(bus_harness: tuple[HassetteHarness, "Hassette", "Bus"]) -> None:
    """Entity in target state at registration time → handler fires with synthetic event."""
    harness, hassette, bus = bus_harness

    await seed(harness, "light.kitchen", "on")

    handler, received, fired = make_collector(hassette)

    await bus.on_state_change(
        "light.kitchen", handler=handler, changed=False, immediate=True, name="immediate_fires_when_state_matches"
    )

    await asyncio.wait_for(fired.wait(), timeout=IMMEDIATE_FIRE_TIMEOUT)

    assert len(received) == 1


async def test_immediate_no_fire_when_state_does_not_match(
    bus_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """Entity in non-target state → no fire (changed_to predicate rejects it)."""
    harness, hassette, bus = bus_harness

    await seed(harness, "light.kitchen", "off")

    handler, received, _fired = make_collector(hassette)

    await bus.on_state_change(
        "light.kitchen", handler=handler, changed_to="on", immediate=True, name="immediate_no_fire_state_mismatch"
    )

    await wait_for(lambda: len(bus.task_bucket) == 0, desc="tasks drain")

    assert received == []


async def test_immediate_no_fire_entity_not_found(bus_harness: tuple[HassetteHarness, "Hassette", "Bus"]) -> None:
    """Entity not in StateProxy → no fire, no error raised."""
    _harness, hassette, bus = bus_harness

    # Do NOT seed state — entity does not exist

    handler, received, _fired = make_collector(hassette)

    await bus.on_state_change(
        "sensor.nonexistent", handler=handler, changed=False, immediate=True, name="immediate_no_fire_entity_not_found"
    )

    await wait_for(lambda: len(bus.task_bucket) == 0, desc="tasks drain")

    assert received == []


async def test_immediate_synthetic_event_structure(bus_harness: tuple[HassetteHarness, "Hassette", "Bus"]) -> None:
    """Synthetic event has old_state=None, new_state=current, ZonedDateTime time_fired, unique context.id."""
    harness, hassette, bus = bus_harness

    await seed(harness, "sensor.temp", "25.5")

    handler, received, fired = make_collector(hassette)

    await bus.on_state_change(
        "sensor.temp", handler=handler, changed=False, immediate=True, name="immediate_synthetic_event_structure"
    )

    await asyncio.wait_for(fired.wait(), timeout=IMMEDIATE_FIRE_TIMEOUT)

    assert len(received) == 1
    event = received[0]
    data = event.payload.data

    assert data.old_state is None
    assert data.new_state is not None
    assert data.new_state["state"] == "25.5"
    assert isinstance(event.payload.time_fired, ZonedDateTime)
    assert event.payload.context.id  # non-empty UUID string
    assert event.payload.context.parent_id is None
    assert event.payload.context.user_id is None


async def test_immediate_with_once_consumes_invocation(bus_harness: tuple[HassetteHarness, "Hassette", "Bus"]) -> None:
    """Immediate fires, subsequent live event does NOT fire (once=True consumed by immediate)."""
    harness, hassette, bus = bus_harness

    await seed(harness, "switch.outlet", "on")

    handler, received, fired = make_collector(hassette)

    await bus.on_state_change(
        "switch.outlet",
        handler=handler,
        changed=False,
        immediate=True,
        once=True,
        name="immediate_once_consumes_invocation",
    )

    await asyncio.wait_for(fired.wait(), timeout=IMMEDIATE_FIRE_TIMEOUT)
    assert len(received) == 1

    # Send a live state change event for the same entity
    live_event = create_state_change_event(entity_id="switch.outlet", old_value="on", new_value="off")
    await hassette.send_event(live_event)

    await wait_for(lambda: len(bus.task_bucket) == 0, desc="tasks drain")

    assert len(received) == 1, f"once=True handler should fire exactly once, fired {len(received)} times"


async def test_immediate_with_debounce(bus_harness: tuple[HassetteHarness, "Hassette", "Bus"]) -> None:
    """Immediate fire passes through the debounce guard (fires after debounce period)."""
    harness, hassette, bus = bus_harness

    await seed(harness, "sensor.motion", "on")

    handler, received, fired = make_collector(hassette)

    await bus.on_state_change(
        "sensor.motion", handler=handler, changed=False, immediate=True, debounce=0.05, name="immediate_with_debounce"
    )

    await asyncio.wait_for(fired.wait(), timeout=IMMEDIATE_FIRE_TIMEOUT)

    assert len(received) == 1


async def test_immediate_glob_entity_rejected(bus_harness: tuple[HassetteHarness, "Hassette", "Bus"]) -> None:
    """immediate=True with a glob entity_id raises ValueError at registration time."""
    _harness, _hassette, bus = bus_harness

    async def handler(event: RawStateChangeEvent) -> None:
        pass

    with pytest.raises(ValueError, match=r"immediate=True.*glob"):
        await bus.on_state_change("light.*", handler=handler, immediate=True, name="immediate_glob_rejected")


async def test_immediate_attribute_change_with_attr_did_change(
    bus_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """on_attribute_change + immediate=True fires when entity present; AttrDidChange returns True for old_state=None."""
    harness, hassette, bus = bus_harness

    await seed(harness, "light.office", "on", attributes={"brightness": 200})

    handler, received, fired = make_collector(hassette)

    await bus.on_attribute_change(
        "light.office", "brightness", handler=handler, immediate=True, name="immediate_attr_change_did_change"
    )

    await asyncio.wait_for(fired.wait(), timeout=IMMEDIATE_FIRE_TIMEOUT)

    assert len(received) == 1
    # Verify old_state is None (synthetic event structure)
    assert received[0].payload.data.old_state is None


async def test_immediate_changed_false_fires_for_any_existing_entity(
    bus_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """changed=False + immediate=True fires for any entity that exists, regardless of state value."""
    harness, hassette, bus = bus_harness

    # Seed entity with arbitrary state
    await seed(harness, "binary_sensor.door", "unavailable")

    handler, received, fired = make_collector(hassette)

    # changed=False means no StateDidChange predicate — any state triggers dispatch
    await bus.on_state_change(
        "binary_sensor.door", handler=handler, changed=False, immediate=True, name="immediate_changed_false_any_entity"
    )

    await asyncio.wait_for(fired.wait(), timeout=IMMEDIATE_FIRE_TIMEOUT)

    assert len(received) == 1
    # Handler fired with state="unavailable" — no state restriction
    assert received[0].payload.data.new_state is not None
    assert received[0].payload.data.new_state["state"] == "unavailable"


async def test_immediate_duration_fires_when_elapsed_exceeds(
    bus_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """Entity held for 10s, duration=5 → fires immediately (elapsed >= duration)."""
    harness, hassette, bus = bus_harness

    # Seed state with last_changed 10 seconds ago
    past = ZonedDateTime.now_in_system_tz().subtract(seconds=10)
    await seed(harness, "switch.boiler", "on", last_changed=past.format_iso())

    handler, received, fired = make_collector(hassette)

    await bus.on_state_change(
        "switch.boiler",
        handler=handler,
        changed=False,
        immediate=True,
        duration=5.0,
        name="immediate_duration_fires_elapsed_exceeds",
    )

    # Elapsed (10s) >= duration (5s) → should fire immediately
    await asyncio.wait_for(fired.wait(), timeout=IMMEDIATE_FIRE_TIMEOUT)

    assert len(received) == 1


async def test_immediate_duration_starts_timer_for_remaining(
    bus_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """Entity held for 3s, duration=5 → timer fires after remaining 2s (plus margin)."""
    harness, hassette, bus = bus_harness

    # Seed state with last_changed 3 seconds ago
    past = ZonedDateTime.now_in_system_tz().subtract(seconds=3)
    await seed(harness, "switch.fan", "on", last_changed=past.format_iso())

    handler, received, fired = make_collector(hassette)

    await bus.on_state_change(
        "switch.fan",
        handler=handler,
        changed=False,
        immediate=True,
        duration=5.0,
        name="immediate_duration_starts_timer_remaining",
    )

    await settle()
    assert len(received) == 0, "Should not have fired immediately — only 3s elapsed of 5s"

    # Should fire after remaining ~2s (plus margin)
    await asyncio.wait_for(fired.wait(), timeout=4.0)
    assert len(received) == 1


async def test_immediate_duration_last_changed_none(bus_harness: tuple[HassetteHarness, "Hassette", "Bus"]) -> None:
    """last_changed missing from state dict → elapsed=0, full timer starts (does NOT fire immediately)."""
    harness, hassette, bus = bus_harness

    state = make_state_dict("switch.pump", "on")
    # Override last_changed to None to simulate missing timestamp — seed() can't express this,
    # since passing last_changed=None falls back to make_state_dict's default of "now".
    state["last_changed"] = None  # pyright: ignore[reportArgumentType]
    await harness.seed_state("switch.pump", state)

    handler, received, _fired = make_collector(hassette)

    await bus.on_state_change(
        "switch.pump",
        handler=handler,
        changed=False,
        immediate=True,
        duration=60.0,  # long enough that we won't wait for it
        name="immediate_duration_last_changed_none",
    )

    # Should NOT fire immediately — full 60s timer starts
    await wait_for(lambda: len(bus.task_bucket) <= 2, desc="timer task registered")
    assert len(received) == 0, "Should not fire when last_changed is None (elapsed=0)"


async def test_immediate_duration_negative_elapsed_clamped(
    bus_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """Clock skew produces last_changed in the future → elapsed clamped to 0, full timer starts."""
    harness, hassette, bus = bus_harness

    # Seed state with last_changed 10 seconds in the FUTURE (clock skew)
    future = ZonedDateTime.now_in_system_tz().add(seconds=10)
    await seed(harness, "switch.heater", "on", last_changed=future.format_iso())

    handler, received, _fired = make_collector(hassette)

    await bus.on_state_change(
        "switch.heater",
        handler=handler,
        changed=False,
        immediate=True,
        duration=5.0,
        name="immediate_duration_negative_elapsed_clamped",
    )

    await settle()
    assert len(received) == 0, "Negative elapsed should be clamped to 0, not fire immediately"


async def test_immediate_duration_attribute_change_always_zero(
    bus_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """on_attribute_change + immediate + duration always starts from zero, even if last_changed is old."""
    harness, hassette, bus = bus_harness

    # Seed state with last_changed 30 seconds ago — would normally fire immediately
    past = ZonedDateTime.now_in_system_tz().subtract(seconds=30)
    await seed(harness, "light.lamp", "on", attributes={"brightness": 200}, last_changed=past.format_iso())

    handler, received, _fired = make_collector(hassette)

    await bus.on_attribute_change(
        "light.lamp",
        "brightness",
        handler=handler,
        immediate=True,
        duration=10.0,  # long duration so we never wait for it
        name="immediate_duration_attr_change_always_zero",
    )

    await settle()
    assert len(received) == 0, (
        "on_attribute_change with immediate+duration should always start from zero, not fire immediately"
    )


async def test_immediate_duration_once_fires_exactly_once(
    bus_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """Immediate + duration + once=True: immediate fire consumes the listener; no subsequent fires."""
    harness, hassette, bus = bus_harness

    # Seed state with last_changed 10s ago (duration=5 → fires immediately)
    past = ZonedDateTime.now_in_system_tz().subtract(seconds=10)
    await seed(harness, "switch.oven", "on", last_changed=past.format_iso())

    handler, received, fired = make_collector(hassette)

    await bus.on_state_change(
        "switch.oven",
        handler=handler,
        changed=False,
        immediate=True,
        duration=5.0,
        once=True,
        name="immediate_duration_once_fires_exactly_once",
    )

    # Should fire immediately (elapsed 10s >= duration 5s)
    await asyncio.wait_for(fired.wait(), timeout=IMMEDIATE_FIRE_TIMEOUT)
    assert len(received) == 1

    # Send a live state change — listener should be consumed (once=True)
    live_event = create_state_change_event(entity_id="switch.oven", old_value="on", new_value="off")
    await hassette.send_event(live_event)

    await wait_for(lambda: len(bus.task_bucket) == 0, desc="tasks drain")

    assert len(received) == 1, f"once=True should fire exactly once, fired {len(received)} times"
