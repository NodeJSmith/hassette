"""Integration tests for immediate-fire (immediate=True) on Bus.on_state_change / on_attribute_change.

Each test builds a fresh harness with bus + state_proxy to avoid cross-test pollution.
State is seeded into the StateProxy via _test_seed_state before the listener is registered.
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
async def imm_harness(test_config) -> AsyncIterator[tuple["Hassette", "Bus"]]:
    """Fresh harness with bus + state_proxy for each test.

    Marks the state proxy ready and enables test-mode so _test_seed_state works.
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
    harness.hassette._test_mode = True  # pyright: ignore[reportAttributeAccessIssue]

    state_proxy = harness.hassette._state_proxy
    assert state_proxy is not None
    state_proxy.mark_ready(reason="imm_harness: mark ready for test")

    hassette = typing.cast("Hassette", harness.hassette)
    bus = hassette._bus
    assert bus is not None

    try:
        yield hassette, bus
    finally:
        await harness.stop()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_immediate_fires_when_state_matches(imm_harness: tuple["Hassette", "Bus"]) -> None:
    """Entity in target state at registration time → handler fires with synthetic event."""
    hassette, bus = imm_harness

    await hassette._state_proxy._test_seed_state(
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


async def test_immediate_no_fire_when_state_does_not_match(imm_harness: tuple["Hassette", "Bus"]) -> None:
    """Entity in non-target state → no fire (changed_to predicate rejects it)."""
    hassette, bus = imm_harness

    await hassette._state_proxy._test_seed_state(
        "light.kitchen",
        make_state_dict("light.kitchen", "off"),
    )

    received: list[RawStateChangeEvent] = []

    async def handler(event: RawStateChangeEvent) -> None:
        received.append(event)

    bus.on_state_change("light.kitchen", handler=handler, changed_to="on", immediate=True)

    # Wait for any immediate-fire tasks to complete
    await asyncio.sleep(0.1)
    await wait_for(lambda: len(hassette._bus.task_bucket) == 0, desc="tasks drain")

    assert received == []


async def test_immediate_no_fire_entity_not_found(imm_harness: tuple["Hassette", "Bus"]) -> None:
    """Entity not in StateProxy → no fire, no error raised."""
    hassette, bus = imm_harness

    # Do NOT seed state — entity does not exist

    received: list[RawStateChangeEvent] = []

    async def handler(event: RawStateChangeEvent) -> None:
        received.append(event)

    bus.on_state_change("sensor.nonexistent", handler=handler, changed=False, immediate=True)

    await asyncio.sleep(0.1)
    await wait_for(lambda: len(hassette._bus.task_bucket) == 0, desc="tasks drain")

    assert received == []


async def test_immediate_synthetic_event_structure(imm_harness: tuple["Hassette", "Bus"]) -> None:
    """Synthetic event has old_state=None, new_state=current, ZonedDateTime time_fired, unique context.id."""
    from whenever import ZonedDateTime

    hassette, bus = imm_harness

    state_dict = make_state_dict("sensor.temp", "25.5")
    await hassette._state_proxy._test_seed_state("sensor.temp", state_dict)

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


async def test_immediate_with_once_consumes_invocation(imm_harness: tuple["Hassette", "Bus"]) -> None:
    """immediate fires, subsequent live event does NOT fire (once=True consumed by immediate)."""
    hassette, bus = imm_harness

    await hassette._state_proxy._test_seed_state(
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

    await asyncio.sleep(0.1)
    await wait_for(lambda: len(hassette._bus.task_bucket) == 0, desc="tasks drain")

    assert call_count == 1, f"once=True handler should fire exactly once, fired {call_count} times"


async def test_immediate_with_debounce(imm_harness: tuple["Hassette", "Bus"]) -> None:
    """immediate fire passes through the debounce guard (fires after debounce period)."""
    hassette, bus = imm_harness

    await hassette._state_proxy._test_seed_state(
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


async def test_immediate_glob_entity_rejected(imm_harness: tuple["Hassette", "Bus"]) -> None:
    """immediate=True with a glob entity_id raises ValueError at registration time."""
    _, bus = imm_harness

    async def handler(event: RawStateChangeEvent) -> None:
        pass

    with pytest.raises(ValueError, match=r"immediate=True.*glob"):
        bus.on_state_change("light.*", handler=handler, immediate=True)


async def test_immediate_attribute_change_with_attr_did_change(imm_harness: tuple["Hassette", "Bus"]) -> None:
    """on_attribute_change + immediate=True fires when entity present; AttrDidChange returns True for old_state=None."""
    hassette, bus = imm_harness

    await hassette._state_proxy._test_seed_state(
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


async def test_immediate_changed_false_fires_for_any_existing_entity(imm_harness: tuple["Hassette", "Bus"]) -> None:
    """changed=False + immediate=True fires for any entity that exists, regardless of state value."""
    hassette, bus = imm_harness

    # Seed entity with arbitrary state
    await hassette._state_proxy._test_seed_state(
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
