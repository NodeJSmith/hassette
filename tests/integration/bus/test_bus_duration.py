"""Integration tests for duration-hold dispatch on Bus.on_state_change / on_attribute_change.

Each test builds a fresh harness with bus + state_proxy.  State is seeded into StateProxy
via harness.seed_state() before listeners are registered.

Positive-fire tests use ``asyncio.sleep(duration + margin)`` to advance the clock — duration
timers are not tracked by dispatch_pending, so await_dispatch_idle() cannot be used to
drain them. Cancellation tests instead await ``DurationTimer.completed`` (via the
``get_duration_timer()`` helper below) so "no fire" assertions are event-gated rather than
timing-dependent.
"""

import asyncio
from typing import TYPE_CHECKING

from hassette.events import RawStateChangeEvent
from hassette.test_utils import wait_for
from hassette.test_utils.harness import HassetteHarness
from hassette.test_utils.helpers import create_state_change_event
from hassette.types import Topic

from .conftest import DURATION, HALF_HOLD, PARTIAL_HOLD, TIMER_COMPLETION_TIMEOUT
from .helpers import drive_state_change, make_collector, seed

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.bus import Bus
    from hassette.bus.duration_timer import DurationTimer

REGISTRATION_SETTLE_DELAY = 0.05  # let listener registration complete before inspecting router state
CANCEL_SETTLE_DELAY = 0.02  # let cancellation-listener add/remove settle before inspecting router state


def get_duration_timer(harness: HassetteHarness, entity_id: str) -> "DurationTimer | None":
    """Get the DurationTimer for the first duration-enabled listener on an entity."""
    topic = f"{Topic.HASS_EVENT_STATE_CHANGED!s}.{entity_id}"
    for listener in harness.bus_service.router.get_topic_listeners(topic):
        if listener.duration_config and listener.duration_config.timer:
            return listener.duration_config.timer
    return None


async def wait_for_timer_completed(timer: "DurationTimer | None", timeout: float = TIMER_COMPLETION_TIMEOUT) -> None:
    """Assert a timer was found and await its current cycle's completion event.

    Centralizes the "no-fire" wait idiom used by cancellation tests: a timer must
    exist (the caller looked it up via ``get_duration_timer()``), and its cycle
    must finish — by firing or by cancellation — within the safety-ceiling timeout.
    """
    assert timer is not None
    await asyncio.wait_for(timer.completed.wait(), timeout=timeout)


async def test_duration_fires_after_held(bus_harness: tuple[HassetteHarness, "Hassette", "Bus"]) -> None:
    """State held for duration → handler fires with the original triggering event."""
    harness, hassette, bus = bus_harness

    handler, received, fired = make_collector(hassette)

    await bus.on_state_change(
        "light.kitchen", changed_to="on", handler=handler, duration=DURATION, name="duration_fires_after_held"
    )

    # StateProxy must be synced too — the timer's re-check reads it
    await drive_state_change(harness, "light.kitchen", "off", "on")

    await asyncio.wait_for(fired.wait(), timeout=DURATION + 0.5)

    assert len(received) == 1
    assert received[0].payload.data.new_state is not None
    assert received[0].payload.data.new_state["state"] == "on"


async def test_duration_cancelled_on_state_exit(bus_harness: tuple[HassetteHarness, "Hassette", "Bus"]) -> None:
    """State changes away before duration elapses → no fire."""
    harness, hassette, bus = bus_harness

    handler, received, _fired = make_collector(hassette)

    await bus.on_state_change(
        "light.kitchen", changed_to="on", handler=handler, duration=DURATION, name="duration_cancelled_on_exit"
    )

    # State enters "on" — timer starts
    await drive_state_change(harness, "light.kitchen", "off", "on")

    # State leaves "on" before duration elapses
    await drive_state_change(harness, "light.kitchen", "on", "off")

    # Wait for the timer's cancellation cycle to complete — no fire should occur
    await wait_for_timer_completed(get_duration_timer(harness, "light.kitchen"))

    assert received == []


async def test_duration_resets_on_re_entry(bus_harness: tuple[HassetteHarness, "Hassette", "Bus"]) -> None:
    """State leaves and returns → timer restarts from zero, fires after second hold."""
    harness, hassette, bus = bus_harness

    handler, received, fired = make_collector(hassette)

    await bus.on_state_change(
        "light.kitchen", changed_to="on", handler=handler, duration=DURATION, name="duration_resets_on_reentry"
    )

    # First entry — timer starts
    await drive_state_change(harness, "light.kitchen", "off", "on")

    # Wait half the duration
    await asyncio.sleep(HALF_HOLD)

    # Exit — timer cancelled
    await drive_state_change(harness, "light.kitchen", "on", "off")

    # Re-enter — timer restarts from zero
    await drive_state_change(harness, "light.kitchen", "off", "on")

    # Wait for full duration from second entry
    await asyncio.wait_for(fired.wait(), timeout=DURATION + 0.5)

    assert len(received) == 1


async def test_duration_double_check_before_fire(bus_harness: tuple[HassetteHarness, "Hassette", "Bus"]) -> None:
    """State reverts between timer start and fire → no fire (state re-verification)."""
    harness, hassette, bus = bus_harness

    handler, received, _fired = make_collector(hassette)

    await bus.on_state_change(
        "light.kitchen", changed_to="on", handler=handler, duration=DURATION, name="duration_double_check"
    )

    # Trigger timer start
    await drive_state_change(harness, "light.kitchen", "off", "on")

    # Revert the state in StateProxy directly (bypassing the event system) WITHOUT sending a
    # cancel event — simulates the state changing back without the cancellation subscription
    # firing. The timer always sleeps the full duration before re-checking state, so it makes
    # no difference to the outcome whether the revert happens immediately after arming or
    # partway through — as long as it happens before the full-duration re-check.
    await seed(harness, "light.kitchen", "off")

    # Wait for timer to fire, re-verify, and complete its cycle
    await wait_for_timer_completed(get_duration_timer(harness, "light.kitchen"))

    # Handler should NOT have fired because re-check fails
    assert received == []


async def test_duration_with_once_fires_exactly_once(bus_harness: tuple[HassetteHarness, "Hassette", "Bus"]) -> None:
    """once=True + duration: fires once; subsequent trigger does not fire."""
    harness, hassette, bus = bus_harness

    handler, received, _fired = make_collector(hassette)

    await bus.on_state_change(
        "light.kitchen", changed_to="on", handler=handler, duration=DURATION, once=True, name="duration_once_fires_once"
    )

    # The timer is attached at registration time, so it's safe to capture before
    # any trigger — the same DurationTimer instance is reused across its lifecycle.
    timer = get_duration_timer(harness, "light.kitchen")

    # First trigger
    await drive_state_change(harness, "light.kitchen", "off", "on")

    # Wait for the fire cycle to complete. DurationTimer only sets `completed`
    # after `on_fire()` (which includes the once-removal finally block) fully
    # returns, so this guarantees the listener is already removed by the time
    # this resolves — no need to sleep past the duration to prove it.
    await wait_for_timer_completed(timer)
    assert len(received) == 1

    # Reset
    await drive_state_change(harness, "light.kitchen", "on", "off")

    # Second trigger — the once-listener was already removed, so no new timer is
    # armed and the handler cannot fire again.
    await drive_state_change(harness, "light.kitchen", "off", "on")

    assert get_duration_timer(harness, "light.kitchen") is None
    assert len(received) == 1, f"once=True handler fired {len(received)} times"


async def test_duration_once_removal_on_exception(bus_harness: tuple[HassetteHarness, "Hassette", "Bus"]) -> None:
    """Handler raises → listener still removed (once contract upheld even on exception)."""
    harness, _hassette, bus = bus_harness

    call_count = 0

    async def handler(_event: RawStateChangeEvent) -> None:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("intentional error in handler")

    await bus.on_state_change(
        "light.kitchen",
        changed_to="on",
        handler=handler,
        duration=DURATION,
        once=True,
        name="duration_once_removal_on_exception",
    )

    # The timer is attached at registration time, so it's safe to capture before
    # any trigger — the same DurationTimer instance is reused across its lifecycle.
    timer = get_duration_timer(harness, "light.kitchen")

    await drive_state_change(harness, "light.kitchen", "off", "on")

    # Wait for the fire cycle to complete. The handler's exception is swallowed by
    # the executor (see CommandExecutor error isolation), so the once-removal
    # finally block still runs and `completed` still fires — this guarantees the
    # listener is already removed by the time this resolves, exception or not.
    await wait_for_timer_completed(timer)
    assert call_count == 1
    assert get_duration_timer(harness, "light.kitchen") is None

    # Fire again — the once-listener was already removed, so no new timer is
    # armed and the handler cannot fire again.
    await drive_state_change(harness, "light.kitchen", "on", "off")
    await drive_state_change(harness, "light.kitchen", "off", "on")

    assert get_duration_timer(harness, "light.kitchen") is None
    assert call_count == 1


async def test_duration_subscription_cancel_stops_timer(bus_harness: tuple[HassetteHarness, "Hassette", "Bus"]) -> None:
    """Cancel subscription while timer pending → no fire, no leak."""
    harness, hassette, bus = bus_harness

    handler, received, _fired = make_collector(hassette)

    sub = await bus.on_state_change(
        "light.kitchen", changed_to="on", handler=handler, duration=DURATION, name="duration_cancel_stops_timer"
    )

    await drive_state_change(harness, "light.kitchen", "off", "on")

    # Cancel before duration elapses
    await asyncio.sleep(PARTIAL_HOLD)
    timer = get_duration_timer(harness, "light.kitchen")
    sub.cancel()

    # Wait for the timer's cancellation cycle to complete
    await wait_for_timer_completed(timer)

    assert received == []


async def test_duration_not_cancelled_by_attribute_refresh(
    bus_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """Attribute-only state_changed (same state value) does NOT cancel timer for on_state_change."""
    harness, hassette, bus = bus_harness

    handler, received, fired = make_collector(hassette)

    await bus.on_state_change(
        "light.kitchen",
        changed_to="on",
        handler=handler,
        duration=DURATION,
        name="duration_not_cancelled_by_attr_refresh",
    )

    # Enter target state
    await drive_state_change(harness, "light.kitchen", "off", "on")

    await asyncio.sleep(PARTIAL_HOLD)

    # Send attribute-only refresh: state remains "on", only attributes change
    event = create_state_change_event(
        entity_id="light.kitchen",
        old_value="on",
        new_value="on",
        new_attrs={"brightness": 200},
    )
    await hassette.send_event(event)
    await harness.bus_service.await_dispatch_idle()

    # Timer should NOT have been cancelled — handler fires after full duration
    await asyncio.wait_for(fired.wait(), timeout=DURATION + 0.5)
    assert len(received) == 1


async def test_duration_multiple_listeners_independent(bus_harness: tuple[HassetteHarness, "Hassette", "Bus"]) -> None:
    """Two listeners with different durations on same entity maintain independent timers."""
    harness, hassette, bus = bus_harness

    short = DURATION
    long_duration = DURATION * 3

    handler_short, received_short, short_fired = make_collector(hassette)
    handler_long, received_long, long_fired = make_collector(hassette)

    await bus.on_state_change(
        "light.kitchen", changed_to="on", handler=handler_short, duration=short, name="duration_multiple_short"
    )
    await bus.on_state_change(
        "light.kitchen", changed_to="on", handler=handler_long, duration=long_duration, name="duration_multiple_long"
    )

    await drive_state_change(harness, "light.kitchen", "off", "on")

    # Short fires first
    await asyncio.wait_for(short_fired.wait(), timeout=short + 0.5)
    assert len(received_short) == 1
    assert len(received_long) == 0

    # Long fires after
    await asyncio.wait_for(long_fired.wait(), timeout=long_duration + 0.5)
    assert len(received_long) == 1


async def test_duration_cancel_listener_uses_framework_tier(
    bus_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """Cancellation listener registered with source_tier='framework'."""
    harness, _hassette, bus = bus_harness

    async def handler(event: RawStateChangeEvent) -> None:
        pass

    await bus.on_state_change(
        "light.kitchen", changed_to="on", handler=handler, duration=DURATION, name="duration_framework_tier"
    )

    # Give time for listener to be registered
    await asyncio.sleep(REGISTRATION_SETTLE_DELAY)
    await wait_for(lambda: len(bus.task_bucket) == 0, desc="registration tasks drain")

    # Collect all registered listeners for the entity topic

    topic = f"{Topic.HASS_EVENT_STATE_CHANGED!s}.light.kitchen"
    listeners = harness.bus_service.router.get_topic_listeners(topic)

    # There should be at least one framework-tier listener (cancellation)
    # The main listener fires only after an event, so the cancel listener is the framework one
    framework_listeners = [lis for lis in listeners if lis.identity.source_tier == "framework"]
    assert len(framework_listeners) >= 1, f"No framework-tier listeners found: {listeners}"


async def test_duration_cancel_listener_same_owner_id(bus_harness: tuple[HassetteHarness, "Hassette", "Bus"]) -> None:
    """Cancellation listener uses same owner_id as main listener — cleaned up by remove_listeners_by_owner."""
    harness, _hassette, bus = bus_harness

    async def handler(event: RawStateChangeEvent) -> None:
        pass

    sub = await bus.on_state_change(
        "light.kitchen", changed_to="on", handler=handler, duration=DURATION, name="duration_cancel_same_owner_id"
    )
    main_listener = sub.listener

    # Wait for timer to start (need a triggering event first)
    await drive_state_change(harness, "light.kitchen", "off", "on")
    await asyncio.sleep(CANCEL_SETTLE_DELAY)

    # Check that cancellation listener has same owner_id

    topic = f"{Topic.HASS_EVENT_STATE_CHANGED!s}.light.kitchen"
    listeners = harness.bus_service.router.get_topic_listeners(topic)
    framework_listeners = [lis for lis in listeners if lis.identity.source_tier == "framework"]

    if framework_listeners:
        assert all(lis.identity.owner_id == main_listener.identity.owner_id for lis in framework_listeners)

    # Cancel subscription — cancellation listener should also be removed
    sub.cancel()
    await asyncio.sleep(CANCEL_SETTLE_DELAY)

    listeners_after = harness.bus_service.router.get_topic_listeners(topic)
    framework_after = [lis for lis in listeners_after if lis.identity.source_tier == "framework"]
    assert len(framework_after) == 0, f"Framework listener not cleaned up: {framework_after}"


async def test_duration_attribute_change_cancel_only_on_predicate_fail(
    bus_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """For on_attribute_change, unrelated attribute changes do not cancel the timer."""
    harness, hassette, bus = bus_harness

    handler, received, fired = make_collector(hassette)

    # Monitor brightness specifically: timer starts when brightness changes
    await bus.on_attribute_change(
        "light.kitchen",
        "brightness",
        changed_to=200,
        handler=handler,
        duration=DURATION,
        name="duration_attr_cancel_predicate_fail",
    )

    # Trigger: brightness changes to 200
    event = create_state_change_event(
        entity_id="light.kitchen",
        old_value="on",
        new_value="on",
        old_attrs={"brightness": 100},
        new_attrs={"brightness": 200},
    )
    await hassette.send_event(event)
    await harness.bus_service.await_dispatch_idle()
    await seed(harness, "light.kitchen", "on")

    # Unrelated attribute change (color_temp only) — should NOT cancel timer
    await asyncio.sleep(PARTIAL_HOLD)
    unrelated = create_state_change_event(
        entity_id="light.kitchen",
        old_value="on",
        new_value="on",
        old_attrs={"brightness": 200, "color_temp": 300},
        new_attrs={"brightness": 200, "color_temp": 400},
    )
    await hassette.send_event(unrelated)
    await harness.bus_service.await_dispatch_idle()

    # Timer should still fire
    await asyncio.wait_for(fired.wait(), timeout=DURATION + 0.5)
    assert len(received) == 1


async def test_duration_handler_receives_original_triggering_event(
    bus_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """Handler receives the original triggering event, not a synthetic recheck event."""
    harness, hassette, bus = bus_harness

    handler, received, fired = make_collector(hassette)

    await bus.on_state_change(
        "light.kitchen", changed_to="on", handler=handler, duration=DURATION, name="duration_original_triggering_event"
    )

    await drive_state_change(harness, "light.kitchen", "off", "on")

    await asyncio.wait_for(fired.wait(), timeout=DURATION + 0.5)

    assert len(received) == 1
    ev = received[0]
    assert ev.payload.data.old_state is not None, "handler should receive original event with old_state"
    assert ev.payload.data.old_state["state"] == "off"
    assert ev.payload.data.new_state is not None
    assert ev.payload.data.new_state["state"] == "on"


async def test_changed_from_with_duration_fires(bus_harness: tuple[HassetteHarness, "Hassette", "Bus"]) -> None:
    """changed_from + duration: timer fires when entity holds target state (hold-predicate split)."""
    harness, hassette, bus = bus_harness

    handler, received, fired = make_collector(hassette)

    await bus.on_state_change(
        "door.front",
        changed_from="closed",
        changed_to="open",
        handler=handler,
        duration=DURATION,
        name="changed_from_duration_fires",
    )

    await drive_state_change(harness, "door.front", "closed", "open")

    await asyncio.wait_for(fired.wait(), timeout=DURATION + 0.5)
    assert len(received) == 1


async def test_changed_from_with_duration_cancels_on_revert(
    bus_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """changed_from + duration: timer cancelled when entity reverts before duration elapses."""
    harness, hassette, bus = bus_harness

    handler, received, _fired = make_collector(hassette)

    await bus.on_state_change(
        "door.front",
        changed_from="closed",
        changed_to="open",
        handler=handler,
        duration=DURATION,
        name="changed_from_duration_cancels_on_revert",
    )

    await drive_state_change(harness, "door.front", "closed", "open")

    # Revert before duration elapses
    await drive_state_change(harness, "door.front", "open", "closed")

    await wait_for_timer_completed(get_duration_timer(harness, "door.front"))
    assert len(received) == 0
