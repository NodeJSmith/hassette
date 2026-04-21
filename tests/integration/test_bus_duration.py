"""Integration tests for duration-hold dispatch on Bus.on_state_change / on_attribute_change.

Each test builds a fresh harness with bus + state_proxy.  State is seeded into StateProxy
via _test_seed_state before listeners are registered.

Duration tests use ``asyncio.sleep(duration + margin)`` to advance the clock — duration
timers are not tracked by dispatch_pending, so await_dispatch_idle() cannot be used to
drain them.
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
from hassette.types import Topic

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.bus import Bus


# ---------------------------------------------------------------------------
# Per-test harness fixture
# ---------------------------------------------------------------------------

DURATION = 0.05  # 50 ms — fast enough for tests


@pytest.fixture
async def dur_harness(test_config) -> AsyncIterator[tuple["Hassette", "Bus"]]:
    """Fresh harness with bus + state_proxy for each test.

    Mirrors the imm_harness pattern from test_bus_immediate.py.
    """
    harness = HassetteHarness(test_config, skip_global_set=False)
    harness.with_bus().with_scheduler().with_state_proxy().with_state_registry()

    api_mock = AsyncMock()
    api_mock.sync = AsyncMock()
    api_mock.get_states_raw = AsyncMock(return_value=[])
    harness.hassette.api = api_mock

    await harness.start()
    harness.hassette._test_mode = True  # pyright: ignore[reportAttributeAccessIssue]

    state_proxy = harness.hassette._state_proxy
    assert state_proxy is not None
    state_proxy.mark_ready(reason="dur_harness: mark ready for test")

    hassette = typing.cast("Hassette", harness.hassette)
    bus = hassette._bus
    assert bus is not None

    try:
        yield hassette, bus
    finally:
        await harness.stop()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def seed(hassette: "Hassette", entity_id: str, state_value: str) -> None:
    """Seed state into the StateProxy."""
    await hassette._state_proxy._test_seed_state(
        entity_id,
        make_state_dict(entity_id, state_value),
    )


async def send_state_change(
    hassette: "Hassette",
    entity_id: str,
    old_value: str,
    new_value: str,
) -> None:
    """Send a state change event into the bus."""
    event = create_state_change_event(entity_id=entity_id, old_value=old_value, new_value=new_value)
    await hassette.send_event(event.topic, event)
    await hassette._bus_service.await_dispatch_idle()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_duration_fires_after_held(dur_harness: tuple["Hassette", "Bus"]) -> None:
    """State held for duration → handler fires with the original triggering event."""
    hassette, bus = dur_harness

    received: list[RawStateChangeEvent] = []
    fired = asyncio.Event()

    async def handler(event: RawStateChangeEvent) -> None:
        received.append(event)
        hassette.task_bucket.post_to_loop(fired.set)

    bus.on_state_change("light.kitchen", changed_to="on", handler=handler, duration=DURATION)

    await send_state_change(hassette, "light.kitchen", "off", "on")

    # Update StateProxy so re-check passes
    await seed(hassette, "light.kitchen", "on")

    await asyncio.wait_for(fired.wait(), timeout=DURATION + 0.5)

    assert len(received) == 1
    assert received[0].payload.data.new_state is not None
    assert received[0].payload.data.new_state["state"] == "on"


async def test_duration_cancelled_on_state_exit(dur_harness: tuple["Hassette", "Bus"]) -> None:
    """State changes away before duration elapses → no fire."""
    hassette, bus = dur_harness

    received: list[RawStateChangeEvent] = []

    async def handler(event: RawStateChangeEvent) -> None:
        received.append(event)

    bus.on_state_change("light.kitchen", changed_to="on", handler=handler, duration=DURATION)

    # State enters "on" — timer starts
    await send_state_change(hassette, "light.kitchen", "off", "on")
    await seed(hassette, "light.kitchen", "on")

    # State leaves "on" before duration elapses
    await send_state_change(hassette, "light.kitchen", "on", "off")
    await seed(hassette, "light.kitchen", "off")

    # Wait longer than duration — no fire should occur
    await asyncio.sleep(DURATION + 0.1)

    assert received == []


async def test_duration_resets_on_re_entry(dur_harness: tuple["Hassette", "Bus"]) -> None:
    """State leaves and returns → timer restarts from zero, fires after second hold."""
    hassette, bus = dur_harness

    received: list[RawStateChangeEvent] = []
    fired = asyncio.Event()

    async def handler(event: RawStateChangeEvent) -> None:
        received.append(event)
        hassette.task_bucket.post_to_loop(fired.set)

    bus.on_state_change("light.kitchen", changed_to="on", handler=handler, duration=DURATION)

    # First entry — timer starts
    await send_state_change(hassette, "light.kitchen", "off", "on")
    await seed(hassette, "light.kitchen", "on")

    # Wait half the duration
    await asyncio.sleep(DURATION * 0.4)

    # Exit — timer cancelled
    await send_state_change(hassette, "light.kitchen", "on", "off")
    await seed(hassette, "light.kitchen", "off")

    # Re-enter — timer restarts from zero
    await send_state_change(hassette, "light.kitchen", "off", "on")
    await seed(hassette, "light.kitchen", "on")

    # Wait for full duration from second entry
    await asyncio.wait_for(fired.wait(), timeout=DURATION + 0.5)

    assert len(received) == 1


async def test_duration_double_check_before_fire(dur_harness: tuple["Hassette", "Bus"]) -> None:
    """State reverts between timer start and fire → no fire (state re-verification)."""
    hassette, bus = dur_harness

    received: list[RawStateChangeEvent] = []

    async def handler(event: RawStateChangeEvent) -> None:
        received.append(event)

    bus.on_state_change("light.kitchen", changed_to="on", handler=handler, duration=DURATION)

    # Trigger timer start
    await send_state_change(hassette, "light.kitchen", "off", "on")
    await seed(hassette, "light.kitchen", "on")

    # Wait most of duration, then revert state in StateProxy WITHOUT sending a cancel event
    # (simulates the state changing back without the cancellation subscription firing)
    await asyncio.sleep(DURATION * 0.8)

    # Revert the state in StateProxy directly (bypassing the event system)
    await seed(hassette, "light.kitchen", "off")

    # Wait for timer to fire and re-verify
    await asyncio.sleep(DURATION * 0.4)

    # Handler should NOT have fired because re-check fails
    assert received == []


async def test_duration_with_once_fires_exactly_once(dur_harness: tuple["Hassette", "Bus"]) -> None:
    """once=True + duration: fires once; subsequent trigger does not fire."""
    hassette, bus = dur_harness

    call_count = 0
    fired = asyncio.Event()

    async def handler(_event: RawStateChangeEvent) -> None:
        nonlocal call_count
        call_count += 1
        hassette.task_bucket.post_to_loop(fired.set)

    bus.on_state_change("light.kitchen", changed_to="on", handler=handler, duration=DURATION, once=True)

    # First trigger
    await send_state_change(hassette, "light.kitchen", "off", "on")
    await seed(hassette, "light.kitchen", "on")
    await asyncio.wait_for(fired.wait(), timeout=DURATION + 0.5)
    assert call_count == 1

    # Reset
    await send_state_change(hassette, "light.kitchen", "on", "off")
    await seed(hassette, "light.kitchen", "off")

    # Second trigger — listener should be gone
    await send_state_change(hassette, "light.kitchen", "off", "on")
    await seed(hassette, "light.kitchen", "on")
    await asyncio.sleep(DURATION + 0.1)

    assert call_count == 1, f"once=True handler fired {call_count} times"


async def test_duration_once_removal_on_exception(dur_harness: tuple["Hassette", "Bus"]) -> None:
    """Handler raises → listener still removed (once contract upheld even on exception)."""
    hassette, bus = dur_harness

    call_count = 0
    fired = asyncio.Event()

    async def handler(_event: RawStateChangeEvent) -> None:
        nonlocal call_count
        call_count += 1
        hassette.task_bucket.post_to_loop(fired.set)
        raise RuntimeError("intentional error in handler")

    bus.on_state_change("light.kitchen", changed_to="on", handler=handler, duration=DURATION, once=True)

    await send_state_change(hassette, "light.kitchen", "off", "on")
    await seed(hassette, "light.kitchen", "on")

    await asyncio.wait_for(fired.wait(), timeout=DURATION + 0.5)
    assert call_count == 1

    # Give time for cleanup
    await asyncio.sleep(0.05)

    # Fire again — listener should be gone
    await send_state_change(hassette, "light.kitchen", "on", "off")
    await seed(hassette, "light.kitchen", "off")
    await send_state_change(hassette, "light.kitchen", "off", "on")
    await seed(hassette, "light.kitchen", "on")
    await asyncio.sleep(DURATION + 0.1)

    assert call_count == 1


async def test_duration_subscription_cancel_stops_timer(dur_harness: tuple["Hassette", "Bus"]) -> None:
    """Cancel subscription while timer pending → no fire, no leak."""
    hassette, bus = dur_harness

    received: list[RawStateChangeEvent] = []

    async def handler(event: RawStateChangeEvent) -> None:
        received.append(event)

    sub = bus.on_state_change("light.kitchen", changed_to="on", handler=handler, duration=DURATION)

    await send_state_change(hassette, "light.kitchen", "off", "on")
    await seed(hassette, "light.kitchen", "on")

    # Cancel before duration elapses
    await asyncio.sleep(DURATION * 0.3)
    sub.cancel()

    # Wait longer than full duration
    await asyncio.sleep(DURATION + 0.1)

    assert received == []


async def test_duration_not_cancelled_by_attribute_refresh(dur_harness: tuple["Hassette", "Bus"]) -> None:
    """Attribute-only state_changed (same state value) does NOT cancel timer for on_state_change."""
    hassette, bus = dur_harness

    received: list[RawStateChangeEvent] = []
    fired = asyncio.Event()

    async def handler(event: RawStateChangeEvent) -> None:
        received.append(event)
        hassette.task_bucket.post_to_loop(fired.set)

    bus.on_state_change("light.kitchen", changed_to="on", handler=handler, duration=DURATION)

    # Enter target state
    await send_state_change(hassette, "light.kitchen", "off", "on")
    await seed(hassette, "light.kitchen", "on")

    await asyncio.sleep(DURATION * 0.3)

    # Send attribute-only refresh: state remains "on", only attributes change
    event = create_state_change_event(
        entity_id="light.kitchen",
        old_value="on",
        new_value="on",
        new_attrs={"brightness": 200},
    )
    await hassette.send_event(event.topic, event)
    await hassette._bus_service.await_dispatch_idle()

    # Timer should NOT have been cancelled — handler fires after full duration
    await asyncio.wait_for(fired.wait(), timeout=DURATION + 0.5)
    assert len(received) == 1


async def test_duration_multiple_listeners_independent(dur_harness: tuple["Hassette", "Bus"]) -> None:
    """Two listeners with different durations on same entity maintain independent timers."""
    hassette, bus = dur_harness

    short = DURATION
    long_ = DURATION * 3

    received_short: list[RawStateChangeEvent] = []
    received_long: list[RawStateChangeEvent] = []
    short_fired = asyncio.Event()
    long_fired = asyncio.Event()

    async def handler_short(event: RawStateChangeEvent) -> None:
        received_short.append(event)
        hassette.task_bucket.post_to_loop(short_fired.set)

    async def handler_long(event: RawStateChangeEvent) -> None:
        received_long.append(event)
        hassette.task_bucket.post_to_loop(long_fired.set)

    bus.on_state_change("light.kitchen", changed_to="on", handler=handler_short, duration=short)
    bus.on_state_change("light.kitchen", changed_to="on", handler=handler_long, duration=long_)

    await send_state_change(hassette, "light.kitchen", "off", "on")
    await seed(hassette, "light.kitchen", "on")

    # Short fires first
    await asyncio.wait_for(short_fired.wait(), timeout=short + 0.5)
    assert len(received_short) == 1
    assert len(received_long) == 0

    # Long fires after
    await asyncio.wait_for(long_fired.wait(), timeout=long_ + 0.5)
    assert len(received_long) == 1


async def test_duration_cancel_listener_uses_framework_tier(dur_harness: tuple["Hassette", "Bus"]) -> None:
    """Cancellation listener registered with source_tier='framework'."""
    hassette, bus = dur_harness

    async def handler(event: RawStateChangeEvent) -> None:
        pass

    bus.on_state_change("light.kitchen", changed_to="on", handler=handler, duration=DURATION)

    # Give time for listener to be registered
    await asyncio.sleep(0.05)
    await wait_for(lambda: len(hassette._bus.task_bucket) == 0, desc="registration tasks drain")

    # Collect all registered listeners for the entity topic

    topic = f"{Topic.HASS_EVENT_STATE_CHANGED!s}.light.kitchen"
    listeners = await hassette._bus_service.router.get_topic_listeners(topic)

    # There should be at least one framework-tier listener (cancellation)
    # The main listener fires only after an event, so the cancel listener is the framework one
    framework_listeners = [lst for lst in listeners if lst.source_tier == "framework"]
    assert len(framework_listeners) >= 1, f"No framework-tier listeners found: {listeners}"


async def test_duration_cancel_listener_same_owner_id(dur_harness: tuple["Hassette", "Bus"]) -> None:
    """Cancellation listener uses same owner_id as main listener — cleaned up by remove_listeners_by_owner."""
    hassette, bus = dur_harness

    async def handler(event: RawStateChangeEvent) -> None:
        pass

    sub = bus.on_state_change("light.kitchen", changed_to="on", handler=handler, duration=DURATION)
    main_listener = sub.listener

    # Wait for timer to start (need a triggering event first)
    await send_state_change(hassette, "light.kitchen", "off", "on")
    await seed(hassette, "light.kitchen", "on")
    await asyncio.sleep(0.02)

    # Check that cancellation listener has same owner_id

    topic = f"{Topic.HASS_EVENT_STATE_CHANGED!s}.light.kitchen"
    listeners = await hassette._bus_service.router.get_topic_listeners(topic)
    framework_listeners = [lst for lst in listeners if lst.source_tier == "framework"]

    if framework_listeners:
        assert all(lst.owner_id == main_listener.owner_id for lst in framework_listeners)

    # Cancel subscription — cancellation listener should also be removed
    sub.cancel()
    await asyncio.sleep(0.02)

    listeners_after = await hassette._bus_service.router.get_topic_listeners(topic)
    framework_after = [lst for lst in listeners_after if lst.source_tier == "framework"]
    assert len(framework_after) == 0, f"Framework listener not cleaned up: {framework_after}"


async def test_duration_attribute_change_cancel_only_on_predicate_fail(
    dur_harness: tuple["Hassette", "Bus"],
) -> None:
    """For on_attribute_change, unrelated attribute changes do not cancel the timer."""
    hassette, bus = dur_harness

    received: list[RawStateChangeEvent] = []
    fired = asyncio.Event()

    async def handler(event: RawStateChangeEvent) -> None:
        received.append(event)
        hassette.task_bucket.post_to_loop(fired.set)

    # Monitor brightness specifically: timer starts when brightness changes
    bus.on_attribute_change("light.kitchen", "brightness", changed_to=200, handler=handler, duration=DURATION)

    # Trigger: brightness changes to 200
    event = create_state_change_event(
        entity_id="light.kitchen",
        old_value="on",
        new_value="on",
        old_attrs={"brightness": 100},
        new_attrs={"brightness": 200},
    )
    await hassette.send_event(event.topic, event)
    await hassette._bus_service.await_dispatch_idle()
    await seed(hassette, "light.kitchen", "on")

    # Unrelated attribute change (color_temp only) — should NOT cancel timer
    await asyncio.sleep(DURATION * 0.3)
    unrelated = create_state_change_event(
        entity_id="light.kitchen",
        old_value="on",
        new_value="on",
        old_attrs={"brightness": 200, "color_temp": 300},
        new_attrs={"brightness": 200, "color_temp": 400},
    )
    await hassette.send_event(unrelated.topic, unrelated)
    await hassette._bus_service.await_dispatch_idle()

    # Timer should still fire
    await asyncio.wait_for(fired.wait(), timeout=DURATION + 0.5)
    assert len(received) == 1
