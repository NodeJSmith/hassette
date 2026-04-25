"""Integration tests for error handler combinations with duration and immediate features.

Covers gaps in the test matrix:
- duration + on_error (app-level and per-listener)
- immediate + on_error (app-level and per-listener)
- immediate + duration + on_error
"""

import asyncio
import typing
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from hassette.bus.error_context import BusErrorContext
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

DURATION = 0.05  # 50 ms — fast enough for tests


@pytest.fixture
async def combo_harness(test_config) -> AsyncIterator[tuple[HassetteHarness, "Hassette", "Bus"]]:
    """Fresh harness with bus + state_proxy for each test."""
    harness = HassetteHarness(test_config, skip_global_set=False)
    harness.with_bus().with_scheduler().with_state_proxy().with_state_registry()

    api_mock = AsyncMock()
    api_mock.sync = AsyncMock()
    api_mock.get_states_raw = AsyncMock(return_value=[])
    harness.hassette.api = api_mock

    await harness.start()

    harness.state_proxy.mark_ready(reason="combo_harness: mark ready for test")

    hassette = typing.cast("Hassette", harness.hassette)
    bus = harness.bus

    try:
        yield harness, hassette, bus
    finally:
        await harness.stop()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def seed(harness: HassetteHarness, entity_id: str, state_value: str) -> None:
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
    event = create_state_change_event(entity_id=entity_id, old_value=old_value, new_value=new_value)
    await harness.hassette.send_event(event.topic, event)
    await harness.bus_service.await_dispatch_idle()


# ---------------------------------------------------------------------------
# duration + error_handler
# ---------------------------------------------------------------------------


async def test_duration_app_level_error_handler(combo_harness: tuple[HassetteHarness, "Hassette", "Bus"]) -> None:
    """Duration timer fires, handler raises → app-level on_error receives the error context."""
    harness, hassette, bus = combo_harness

    error_contexts: list[BusErrorContext] = []
    error_ran = asyncio.Event()

    async def on_error(ctx: BusErrorContext) -> None:
        error_contexts.append(ctx)
        hassette.task_bucket.post_to_loop(error_ran.set)

    async def bad_handler(_event: RawStateChangeEvent) -> None:
        raise ValueError("duration handler failed")

    bus.on_error(on_error)
    bus.on_state_change("light.kitchen", changed_to="on", handler=bad_handler, duration=DURATION)

    await send_state_change(harness, "light.kitchen", "off", "on")
    await seed(harness, "light.kitchen", "on")

    await asyncio.wait_for(error_ran.wait(), timeout=DURATION + 1.0)

    assert len(error_contexts) == 1
    assert isinstance(error_contexts[0].exception, ValueError)
    assert str(error_contexts[0].exception) == "duration handler failed"
    assert "bad_handler" in error_contexts[0].listener_name


async def test_duration_per_listener_error_handler_wins(
    combo_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """Duration fire + per-listener on_error takes precedence over app-level handler."""
    harness, hassette, bus = combo_harness

    app_level_calls: list[BusErrorContext] = []
    per_listener_calls: list[BusErrorContext] = []
    per_listener_ran = asyncio.Event()

    async def app_level_handler(ctx: BusErrorContext) -> None:
        app_level_calls.append(ctx)

    async def per_listener_handler(ctx: BusErrorContext) -> None:
        per_listener_calls.append(ctx)
        hassette.task_bucket.post_to_loop(per_listener_ran.set)

    async def bad_handler(_event: RawStateChangeEvent) -> None:
        raise RuntimeError("per-listener duration failure")

    bus.on_error(app_level_handler)
    bus.on_state_change(
        "light.kitchen",
        changed_to="on",
        handler=bad_handler,
        duration=DURATION,
        on_error=per_listener_handler,
    )

    await send_state_change(harness, "light.kitchen", "off", "on")
    await seed(harness, "light.kitchen", "on")

    await asyncio.wait_for(per_listener_ran.wait(), timeout=DURATION + 1.0)
    # negative-assertion: no event-driven alternative
    await asyncio.sleep(0.05)

    assert len(per_listener_calls) == 1
    assert len(app_level_calls) == 0
    assert isinstance(per_listener_calls[0].exception, RuntimeError)


async def test_duration_error_handler_receives_original_event(
    combo_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """Error context from a duration fire carries the original triggering event."""
    harness, hassette, bus = combo_harness

    error_contexts: list[BusErrorContext] = []
    error_ran = asyncio.Event()

    async def on_error(ctx: BusErrorContext) -> None:
        error_contexts.append(ctx)
        hassette.task_bucket.post_to_loop(error_ran.set)

    async def bad_handler(_event: RawStateChangeEvent) -> None:
        raise TypeError("check event in context")

    bus.on_error(on_error)
    bus.on_state_change("light.kitchen", changed_to="on", handler=bad_handler, duration=DURATION)

    await send_state_change(harness, "light.kitchen", "off", "on")
    await seed(harness, "light.kitchen", "on")

    await asyncio.wait_for(error_ran.wait(), timeout=DURATION + 1.0)

    assert len(error_contexts) == 1
    ctx = error_contexts[0]
    assert isinstance(ctx.event, RawStateChangeEvent)
    assert ctx.event.payload.data.new_state is not None
    assert ctx.event.payload.data.new_state["state"] == "on"


async def test_duration_once_error_handler_and_removal(
    combo_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """once=True + duration + on_error: handler raises, error handler fires, listener still removed."""
    harness, hassette, bus = combo_harness

    error_contexts: list[BusErrorContext] = []
    error_ran = asyncio.Event()
    call_count = 0

    async def on_error(ctx: BusErrorContext) -> None:
        error_contexts.append(ctx)
        hassette.task_bucket.post_to_loop(error_ran.set)

    async def bad_handler(_event: RawStateChangeEvent) -> None:
        nonlocal call_count
        call_count += 1
        raise ValueError("once + duration + error")

    bus.on_error(on_error)
    bus.on_state_change("light.kitchen", changed_to="on", handler=bad_handler, duration=DURATION, once=True)

    await send_state_change(harness, "light.kitchen", "off", "on")
    await seed(harness, "light.kitchen", "on")

    await asyncio.wait_for(error_ran.wait(), timeout=DURATION + 1.0)
    assert call_count == 1
    assert len(error_contexts) == 1

    await wait_for(lambda: not bus.task_bucket.pending_tasks(), desc="tasks drain")

    # Second trigger — listener should be gone (once contract upheld despite exception)
    await send_state_change(harness, "light.kitchen", "on", "off")
    await seed(harness, "light.kitchen", "off")
    await send_state_change(harness, "light.kitchen", "off", "on")
    await seed(harness, "light.kitchen", "on")
    await asyncio.sleep(DURATION + 0.1)

    assert call_count == 1, f"once=True handler fired {call_count} times despite error"
    assert len(error_contexts) == 1


# ---------------------------------------------------------------------------
# immediate + error_handler
# ---------------------------------------------------------------------------


async def test_immediate_app_level_error_handler(combo_harness: tuple[HassetteHarness, "Hassette", "Bus"]) -> None:
    """Immediate fire handler raises → app-level on_error receives the error context."""
    harness, hassette, bus = combo_harness

    await harness.seed_state("light.kitchen", make_state_dict("light.kitchen", "on"))

    error_contexts: list[BusErrorContext] = []
    error_ran = asyncio.Event()

    async def on_error(ctx: BusErrorContext) -> None:
        error_contexts.append(ctx)
        hassette.task_bucket.post_to_loop(error_ran.set)

    async def bad_handler(_event: RawStateChangeEvent) -> None:
        raise ValueError("immediate handler failed")

    bus.on_error(on_error)
    bus.on_state_change("light.kitchen", handler=bad_handler, changed=False, immediate=True)

    await asyncio.wait_for(error_ran.wait(), timeout=2.0)

    assert len(error_contexts) == 1
    assert isinstance(error_contexts[0].exception, ValueError)
    assert str(error_contexts[0].exception) == "immediate handler failed"
    assert "bad_handler" in error_contexts[0].listener_name


async def test_immediate_per_listener_error_handler_wins(
    combo_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """Immediate fire + per-listener on_error takes precedence over app-level handler."""
    harness, hassette, bus = combo_harness

    await harness.seed_state("switch.outlet", make_state_dict("switch.outlet", "on"))

    app_level_calls: list[BusErrorContext] = []
    per_listener_calls: list[BusErrorContext] = []
    per_listener_ran = asyncio.Event()

    async def app_level_handler(ctx: BusErrorContext) -> None:
        app_level_calls.append(ctx)

    async def per_listener_handler(ctx: BusErrorContext) -> None:
        per_listener_calls.append(ctx)
        hassette.task_bucket.post_to_loop(per_listener_ran.set)

    async def bad_handler(_event: RawStateChangeEvent) -> None:
        raise RuntimeError("per-listener immediate failure")

    bus.on_error(app_level_handler)
    bus.on_state_change(
        "switch.outlet",
        handler=bad_handler,
        changed=False,
        immediate=True,
        on_error=per_listener_handler,
    )

    await asyncio.wait_for(per_listener_ran.wait(), timeout=2.0)
    # negative-assertion: no event-driven alternative
    await asyncio.sleep(0.05)

    assert len(per_listener_calls) == 1
    assert len(app_level_calls) == 0
    assert isinstance(per_listener_calls[0].exception, RuntimeError)


async def test_immediate_once_error_handler_and_removal(
    combo_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """immediate + once=True + on_error: handler raises, error handler fires, listener consumed."""
    harness, hassette, bus = combo_harness

    await harness.seed_state("switch.outlet", make_state_dict("switch.outlet", "on"))

    error_contexts: list[BusErrorContext] = []
    error_ran = asyncio.Event()
    call_count = 0

    async def on_error(ctx: BusErrorContext) -> None:
        error_contexts.append(ctx)
        hassette.task_bucket.post_to_loop(error_ran.set)

    async def bad_handler(_event: RawStateChangeEvent) -> None:
        nonlocal call_count
        call_count += 1
        raise ValueError("immediate + once + error")

    bus.on_error(on_error)
    bus.on_state_change("switch.outlet", handler=bad_handler, changed=False, immediate=True, once=True)

    await asyncio.wait_for(error_ran.wait(), timeout=2.0)
    assert call_count == 1
    assert len(error_contexts) == 1

    # Live event — listener should be consumed
    live_event = create_state_change_event(entity_id="switch.outlet", old_value="on", new_value="off")
    await hassette.send_event(live_event.topic, live_event)
    await wait_for(lambda: len(bus.task_bucket) == 0, desc="tasks drain")

    assert call_count == 1, f"once=True handler fired {call_count} times despite error"


async def test_immediate_error_handler_receives_synthetic_event(
    combo_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """Error context from an immediate fire carries the synthetic event (old_state=None)."""
    harness, hassette, bus = combo_harness

    await harness.seed_state("sensor.temp", make_state_dict("sensor.temp", "25.5"))

    error_contexts: list[BusErrorContext] = []
    error_ran = asyncio.Event()

    async def on_error(ctx: BusErrorContext) -> None:
        error_contexts.append(ctx)
        hassette.task_bucket.post_to_loop(error_ran.set)

    async def bad_handler(_event: RawStateChangeEvent) -> None:
        raise TypeError("check synthetic event in error context")

    bus.on_error(on_error)
    bus.on_state_change("sensor.temp", handler=bad_handler, changed=False, immediate=True)

    await asyncio.wait_for(error_ran.wait(), timeout=2.0)

    assert len(error_contexts) == 1
    ctx = error_contexts[0]
    assert isinstance(ctx.event, RawStateChangeEvent)
    assert ctx.event.payload.data.old_state is None
    assert ctx.event.payload.data.new_state is not None
    assert ctx.event.payload.data.new_state["state"] == "25.5"


# ---------------------------------------------------------------------------
# immediate + duration + error_handler (three-way combo)
# ---------------------------------------------------------------------------


async def test_immediate_duration_elapsed_exceeds_error_handler(
    combo_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """immediate + duration (elapsed >= duration) + on_error: fires immediately, error handler called."""
    from whenever import ZonedDateTime

    harness, hassette, bus = combo_harness

    past = ZonedDateTime.now_in_system_tz().subtract(seconds=10)
    await harness.seed_state(
        "switch.boiler",
        make_state_dict("switch.boiler", "on", last_changed=past.format_iso()),
    )

    error_contexts: list[BusErrorContext] = []
    error_ran = asyncio.Event()

    async def on_error(ctx: BusErrorContext) -> None:
        error_contexts.append(ctx)
        hassette.task_bucket.post_to_loop(error_ran.set)

    async def bad_handler(_event: RawStateChangeEvent) -> None:
        raise ValueError("immediate + duration + error (elapsed exceeds)")

    bus.on_error(on_error)
    bus.on_state_change(
        "switch.boiler",
        handler=bad_handler,
        changed=False,
        immediate=True,
        duration=5.0,
    )

    await asyncio.wait_for(error_ran.wait(), timeout=2.0)

    assert len(error_contexts) == 1
    assert isinstance(error_contexts[0].exception, ValueError)
    assert "bad_handler" in error_contexts[0].listener_name


async def test_immediate_duration_remaining_timer_error_handler(
    combo_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """immediate + duration (elapsed < duration) + on_error: timer fires after remaining, error handler called."""
    from whenever import ZonedDateTime

    harness, hassette, bus = combo_harness

    past = ZonedDateTime.now_in_system_tz().subtract(seconds=3)
    await harness.seed_state(
        "switch.fan",
        make_state_dict("switch.fan", "on", last_changed=past.format_iso()),
    )

    error_contexts: list[BusErrorContext] = []
    error_ran = asyncio.Event()

    async def on_error(ctx: BusErrorContext) -> None:
        error_contexts.append(ctx)
        hassette.task_bucket.post_to_loop(error_ran.set)

    async def bad_handler(_event: RawStateChangeEvent) -> None:
        raise RuntimeError("timer fire after remaining")

    bus.on_error(on_error)
    bus.on_state_change(
        "switch.fan",
        handler=bad_handler,
        changed=False,
        immediate=True,
        duration=5.0,
    )

    # negative-assertion: no event-driven alternative
    await asyncio.sleep(0.05)
    assert len(error_contexts) == 0

    # Should fire after remaining ~2s
    await asyncio.wait_for(error_ran.wait(), timeout=4.0)

    assert len(error_contexts) == 1
    assert isinstance(error_contexts[0].exception, RuntimeError)


async def test_immediate_duration_per_listener_error_handler(
    combo_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """Three-way combo with per-listener on_error: per-listener wins over app-level."""
    from whenever import ZonedDateTime

    harness, hassette, bus = combo_harness

    past = ZonedDateTime.now_in_system_tz().subtract(seconds=10)
    await harness.seed_state(
        "switch.heater",
        make_state_dict("switch.heater", "on", last_changed=past.format_iso()),
    )

    app_level_calls: list[BusErrorContext] = []
    per_listener_calls: list[BusErrorContext] = []
    per_listener_ran = asyncio.Event()

    async def app_level_handler(ctx: BusErrorContext) -> None:
        app_level_calls.append(ctx)

    async def per_listener_handler(ctx: BusErrorContext) -> None:
        per_listener_calls.append(ctx)
        hassette.task_bucket.post_to_loop(per_listener_ran.set)

    async def bad_handler(_event: RawStateChangeEvent) -> None:
        raise TypeError("three-way combo per-listener")

    bus.on_error(app_level_handler)
    bus.on_state_change(
        "switch.heater",
        handler=bad_handler,
        changed=False,
        immediate=True,
        duration=5.0,
        on_error=per_listener_handler,
    )

    await asyncio.wait_for(per_listener_ran.wait(), timeout=2.0)
    # negative-assertion: no event-driven alternative
    await asyncio.sleep(0.05)

    assert len(per_listener_calls) == 1
    assert len(app_level_calls) == 0
    assert isinstance(per_listener_calls[0].exception, TypeError)
