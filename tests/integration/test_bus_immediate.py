"""Integration tests for immediate-fire (immediate=True) on Bus.on_state_change / on_attribute_change.

Each test builds a fresh harness with bus + state_proxy to avoid cross-test pollution.
State is seeded into the StateProxy via harness.seed_state() before the listener is registered.
"""

import asyncio
import typing
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from hassette.events import RawStateChangeEvent
from hassette.test_utils import make_state_dict, wait_for
from hassette.test_utils.harness import HassetteHarness
from hassette.test_utils.helpers import create_state_change_event

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.bus import Bus


# ---------------------------------------------------------------------------
# Per-test harness fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def imm_harness(test_config) -> AsyncIterator[tuple[HassetteHarness, "Hassette", "Bus"]]:
    """Fresh harness with bus + state_proxy for each test.

    Marks the state proxy ready. State is seeded via harness.seed_state().
    The api mock returns an empty state list so _load_cache succeeds without HTTP.
    """
    harness = HassetteHarness(test_config, skip_global_set=False)
    harness.with_bus().with_scheduler().with_state_proxy().with_state_registry()

    # Pre-configure api mock before harness.start() so StateProxy._load_cache won't fail
    api_mock = AsyncMock()
    api_mock.sync = AsyncMock()
    api_mock.get_states_raw = AsyncMock(return_value=[])
    harness.hassette.api = api_mock

    await harness.start()

    harness.state_proxy.mark_ready(reason="imm_harness: mark ready for test")

    hassette = typing.cast("Hassette", harness.hassette)
    bus = harness.bus

    try:
        yield harness, hassette, bus
    finally:
        await harness.stop()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_immediate_fires_when_state_matches(imm_harness: tuple[HassetteHarness, "Hassette", "Bus"]) -> None:
    """Entity in target state at registration time → handler fires with synthetic event."""
    harness, hassette, bus = imm_harness

    await harness.seed_state(
        "light.kitchen",
        make_state_dict("light.kitchen", "on"),
    )

    received: list[RawStateChangeEvent] = []
    fired = asyncio.Event()

    async def handler(event: RawStateChangeEvent) -> None:
        received.append(event)
        hassette.task_bucket.post_to_loop(fired.set)

    bus.on_state_change("light.kitchen", handler=handler, changed=False, immediate=True)

    await asyncio.wait_for(fired.wait(), timeout=2.0)

    assert len(received) == 1


async def test_immediate_no_fire_when_state_does_not_match(
    imm_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """Entity in non-target state → no fire (changed_to predicate rejects it)."""
    harness, _hassette, bus = imm_harness

    await harness.seed_state(
        "light.kitchen",
        make_state_dict("light.kitchen", "off"),
    )

    received: list[RawStateChangeEvent] = []

    async def handler(event: RawStateChangeEvent) -> None:
        received.append(event)

    bus.on_state_change("light.kitchen", handler=handler, changed_to="on", immediate=True)

    await wait_for(lambda: len(bus.task_bucket) == 0, desc="tasks drain")

    assert received == []


async def test_immediate_no_fire_entity_not_found(imm_harness: tuple[HassetteHarness, "Hassette", "Bus"]) -> None:
    """Entity not in StateProxy → no fire, no error raised."""
    _harness, _hassette, bus = imm_harness

    # Do NOT seed state — entity does not exist

    received: list[RawStateChangeEvent] = []

    async def handler(event: RawStateChangeEvent) -> None:
        received.append(event)

    bus.on_state_change("sensor.nonexistent", handler=handler, changed=False, immediate=True)

    await wait_for(lambda: len(bus.task_bucket) == 0, desc="tasks drain")

    assert received == []


async def test_immediate_synthetic_event_structure(imm_harness: tuple[HassetteHarness, "Hassette", "Bus"]) -> None:
    """Synthetic event has old_state=None, new_state=current, ZonedDateTime time_fired, unique context.id."""
    from whenever import ZonedDateTime

    harness, hassette, bus = imm_harness

    state_dict = make_state_dict("sensor.temp", "25.5")
    await harness.seed_state("sensor.temp", state_dict)

    received: list[RawStateChangeEvent] = []
    fired = asyncio.Event()

    async def handler(event: RawStateChangeEvent) -> None:
        received.append(event)
        hassette.task_bucket.post_to_loop(fired.set)

    bus.on_state_change("sensor.temp", handler=handler, changed=False, immediate=True)

    await asyncio.wait_for(fired.wait(), timeout=2.0)

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


async def test_immediate_with_once_consumes_invocation(imm_harness: tuple[HassetteHarness, "Hassette", "Bus"]) -> None:
    """immediate fires, subsequent live event does NOT fire (once=True consumed by immediate)."""
    harness, hassette, bus = imm_harness

    await harness.seed_state(
        "switch.outlet",
        make_state_dict("switch.outlet", "on"),
    )

    call_count = 0
    fired = asyncio.Event()

    async def handler(_event: RawStateChangeEvent) -> None:
        nonlocal call_count
        call_count += 1
        hassette.task_bucket.post_to_loop(fired.set)

    bus.on_state_change("switch.outlet", handler=handler, changed=False, immediate=True, once=True)

    await asyncio.wait_for(fired.wait(), timeout=2.0)
    assert call_count == 1

    # Send a live state change event for the same entity
    live_event = create_state_change_event(entity_id="switch.outlet", old_value="on", new_value="off")
    await hassette.send_event(live_event.topic, live_event)

    await wait_for(lambda: len(bus.task_bucket) == 0, desc="tasks drain")

    assert call_count == 1, f"once=True handler should fire exactly once, fired {call_count} times"


async def test_immediate_with_debounce(imm_harness: tuple[HassetteHarness, "Hassette", "Bus"]) -> None:
    """immediate fire passes through the debounce guard (fires after debounce period)."""
    harness, hassette, bus = imm_harness

    await harness.seed_state(
        "sensor.motion",
        make_state_dict("sensor.motion", "on"),
    )

    received: list[RawStateChangeEvent] = []
    fired = asyncio.Event()

    async def handler(event: RawStateChangeEvent) -> None:
        received.append(event)
        hassette.task_bucket.post_to_loop(fired.set)

    bus.on_state_change("sensor.motion", handler=handler, changed=False, immediate=True, debounce=0.05)

    await asyncio.wait_for(fired.wait(), timeout=2.0)

    assert len(received) == 1


async def test_immediate_glob_entity_rejected(imm_harness: tuple[HassetteHarness, "Hassette", "Bus"]) -> None:
    """immediate=True with a glob entity_id raises ValueError at registration time."""
    _harness, _hassette, bus = imm_harness

    async def handler(event: RawStateChangeEvent) -> None:
        pass

    with pytest.raises(ValueError, match=r"immediate=True.*glob"):
        bus.on_state_change("light.*", handler=handler, immediate=True)


async def test_immediate_attribute_change_with_attr_did_change(
    imm_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """on_attribute_change + immediate=True fires when entity present; AttrDidChange returns True for old_state=None."""
    harness, hassette, bus = imm_harness

    await harness.seed_state(
        "light.office",
        make_state_dict("light.office", "on", attributes={"brightness": 200}),
    )

    received: list[RawStateChangeEvent] = []
    fired = asyncio.Event()

    async def handler(event: RawStateChangeEvent) -> None:
        received.append(event)
        hassette.task_bucket.post_to_loop(fired.set)

    bus.on_attribute_change("light.office", "brightness", handler=handler, immediate=True)

    await asyncio.wait_for(fired.wait(), timeout=2.0)

    assert len(received) == 1
    # Verify old_state is None (synthetic event structure)
    assert received[0].payload.data.old_state is None


async def test_immediate_changed_false_fires_for_any_existing_entity(
    imm_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """changed=False + immediate=True fires for any entity that exists, regardless of state value."""
    harness, hassette, bus = imm_harness

    # Seed entity with arbitrary state
    await harness.seed_state(
        "binary_sensor.door",
        make_state_dict("binary_sensor.door", "unavailable"),
    )

    received: list[RawStateChangeEvent] = []
    fired = asyncio.Event()

    async def handler(event: RawStateChangeEvent) -> None:
        received.append(event)
        hassette.task_bucket.post_to_loop(fired.set)

    # changed=False means no StateDidChange predicate — any state triggers dispatch
    bus.on_state_change("binary_sensor.door", handler=handler, changed=False, immediate=True)

    await asyncio.wait_for(fired.wait(), timeout=2.0)

    assert len(received) == 1
    # Handler fired with state="unavailable" — no state restriction
    assert received[0].payload.data.new_state is not None
    assert received[0].payload.data.new_state["state"] == "unavailable"


# ---------------------------------------------------------------------------
# immediate + duration combo tests (WP05)
# ---------------------------------------------------------------------------


async def test_immediate_duration_fires_when_elapsed_exceeds(
    imm_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """Entity held for 10s, duration=5 → fires immediately (elapsed >= duration)."""

    from whenever import ZonedDateTime

    harness, hassette, bus = imm_harness

    # Seed state with last_changed 10 seconds ago
    past = ZonedDateTime.now_in_system_tz().subtract(seconds=10)
    await harness.seed_state(
        "switch.boiler",
        make_state_dict("switch.boiler", "on", last_changed=past.format_iso()),
    )

    received: list[RawStateChangeEvent] = []
    fired = asyncio.Event()

    async def handler(event: RawStateChangeEvent) -> None:
        received.append(event)
        hassette.task_bucket.post_to_loop(fired.set)

    bus.on_state_change(
        "switch.boiler",
        handler=handler,
        changed=False,
        immediate=True,
        duration=5.0,
    )

    # Elapsed (10s) >= duration (5s) → should fire immediately
    await asyncio.wait_for(fired.wait(), timeout=2.0)

    assert len(received) == 1


async def test_immediate_duration_starts_timer_for_remaining(
    imm_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """Entity held for 3s, duration=5 → timer fires after remaining 2s (plus margin)."""
    from whenever import ZonedDateTime

    harness, hassette, bus = imm_harness

    # Seed state with last_changed 3 seconds ago
    past = ZonedDateTime.now_in_system_tz().subtract(seconds=3)
    await harness.seed_state(
        "switch.fan",
        make_state_dict("switch.fan", "on", last_changed=past.format_iso()),
    )

    received: list[RawStateChangeEvent] = []
    fired = asyncio.Event()

    async def handler(event: RawStateChangeEvent) -> None:
        received.append(event)
        hassette.task_bucket.post_to_loop(fired.set)

    bus.on_state_change(
        "switch.fan",
        handler=handler,
        changed=False,
        immediate=True,
        duration=5.0,
    )

    # negative-assertion: no event-driven alternative
    await asyncio.sleep(0.05)
    assert len(received) == 0, "Should not have fired immediately — only 3s elapsed of 5s"

    # Should fire after remaining ~2s (plus margin)
    await asyncio.wait_for(fired.wait(), timeout=4.0)
    assert len(received) == 1


async def test_immediate_duration_last_changed_none(imm_harness: tuple[HassetteHarness, "Hassette", "Bus"]) -> None:
    """last_changed missing from state dict → elapsed=0, full timer starts (does NOT fire immediately)."""
    harness, _hassette, bus = imm_harness

    state = make_state_dict("switch.pump", "on")
    # Override last_changed to None to simulate missing timestamp
    state["last_changed"] = None  # pyright: ignore[reportArgumentType]
    await harness.seed_state("switch.pump", state)

    received: list[RawStateChangeEvent] = []

    async def handler(event: RawStateChangeEvent) -> None:
        received.append(event)

    bus.on_state_change(
        "switch.pump",
        handler=handler,
        changed=False,
        immediate=True,
        duration=60.0,  # long enough that we won't wait for it
    )

    # Should NOT fire immediately — full 60s timer starts
    await wait_for(lambda: len(bus.task_bucket) <= 2, desc="timer task registered")
    assert len(received) == 0, "Should not fire when last_changed is None (elapsed=0)"


async def test_immediate_duration_negative_elapsed_clamped(
    imm_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """Clock skew produces last_changed in the future → elapsed clamped to 0, full timer starts."""
    from whenever import ZonedDateTime

    harness, _hassette, bus = imm_harness

    # Seed state with last_changed 10 seconds in the FUTURE (clock skew)
    future = ZonedDateTime.now_in_system_tz().add(seconds=10)
    await harness.seed_state(
        "switch.heater",
        make_state_dict("switch.heater", "on", last_changed=future.format_iso()),
    )

    received: list[RawStateChangeEvent] = []

    async def handler(event: RawStateChangeEvent) -> None:
        received.append(event)

    bus.on_state_change(
        "switch.heater",
        handler=handler,
        changed=False,
        immediate=True,
        duration=5.0,
    )

    # negative-assertion: no event-driven alternative
    await asyncio.sleep(0.05)
    assert len(received) == 0, "Negative elapsed should be clamped to 0, not fire immediately"


async def test_immediate_duration_attribute_change_always_zero(
    imm_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """on_attribute_change + immediate + duration always starts from zero, even if last_changed is old."""
    from whenever import ZonedDateTime

    harness, _hassette, bus = imm_harness

    # Seed state with last_changed 30 seconds ago — would normally fire immediately
    past = ZonedDateTime.now_in_system_tz().subtract(seconds=30)
    await harness.seed_state(
        "light.lamp",
        make_state_dict("light.lamp", "on", attributes={"brightness": 200}, last_changed=past.format_iso()),
    )

    received: list[RawStateChangeEvent] = []

    async def handler(event: RawStateChangeEvent) -> None:
        received.append(event)

    bus.on_attribute_change(
        "light.lamp",
        "brightness",
        handler=handler,
        immediate=True,
        duration=10.0,  # long duration so we never wait for it
    )

    # negative-assertion: no event-driven alternative
    await asyncio.sleep(0.05)
    assert len(received) == 0, (
        "on_attribute_change with immediate+duration should always start from zero, not fire immediately"
    )


async def test_immediate_duration_once_fires_exactly_once(
    imm_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """immediate + duration + once=True: immediate fire consumes the listener; no subsequent fires."""
    from whenever import ZonedDateTime

    harness, hassette, bus = imm_harness

    # Seed state with last_changed 10s ago (duration=5 → fires immediately)
    past = ZonedDateTime.now_in_system_tz().subtract(seconds=10)
    await harness.seed_state(
        "switch.oven",
        make_state_dict("switch.oven", "on", last_changed=past.format_iso()),
    )

    call_count = 0
    fired = asyncio.Event()

    async def handler(_event: RawStateChangeEvent) -> None:
        nonlocal call_count
        call_count += 1
        hassette.task_bucket.post_to_loop(fired.set)

    bus.on_state_change(
        "switch.oven",
        handler=handler,
        changed=False,
        immediate=True,
        duration=5.0,
        once=True,
    )

    # Should fire immediately (elapsed 10s >= duration 5s)
    await asyncio.wait_for(fired.wait(), timeout=2.0)
    assert call_count == 1

    # Send a live state change — listener should be consumed (once=True)
    from hassette.test_utils.helpers import create_state_change_event

    live_event = create_state_change_event(entity_id="switch.oven", old_value="on", new_value="off")
    await hassette.send_event(live_event.topic, live_event)

    await wait_for(lambda: len(bus.task_bucket) == 0, desc="tasks drain")

    assert call_count == 1, f"once=True should fire exactly once, fired {call_count} times"
