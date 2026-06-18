"""Tests for the BusService dispatch concurrency semaphore (#678, backpressure epic #72).

The bus fans an event out to one task per matching listener. These tests pin the bound:
no more than ``max_concurrent_dispatches`` handlers run at once, slots are released on every
completion path, and behavior under the limit is unchanged.
"""

import asyncio
from unittest.mock import MagicMock

from hassette.core.bus_service import _DISPATCH_SATURATION_WARN_RATE_LIMIT_SECS, BusService
from hassette.events.base import Event
from hassette.test_utils.helpers import create_listener

from .conftest import make_bus_service

TEST_TIMEOUT = 1.0


def make_event() -> Event:
    """Minimal non-hass event — routes to its base topic verbatim (no state_changed expansion)."""
    return MagicMock(spec=Event)


def register_listeners(svc: BusService, topic: str, count: int) -> None:
    for i in range(count):
        listener = create_listener(topic=topic, name=f"listener_{i}", owner_id=f"owner_{i}")
        svc.router.add_route(listener.topic, listener)


async def assert_all_slots_reacquirable(svc: BusService, count: int) -> None:
    """Acquire every dispatch slot without blocking — proves no permit leaked on completion."""
    for _ in range(count):
        await asyncio.wait_for(svc._dispatch_semaphore.acquire(), timeout=TEST_TIMEOUT)
    assert svc._dispatch_semaphore.locked()


async def test_dispatch_bounds_concurrent_handlers() -> None:
    """With max=2 and 4 matching listeners, only 2 handlers run at once; all eventually run."""
    svc = make_bus_service(max_concurrent_dispatches=2)
    register_listeners(svc, "test.topic", 4)

    gate = asyncio.Event()
    running = 0
    peak = 0
    completed = 0
    two_running = asyncio.Event()

    async def blocking_dispatch(_route, _event, _listener) -> None:
        nonlocal running, peak, completed
        running += 1
        peak = max(peak, running)
        if running >= 2:
            two_running.set()
        try:
            await gate.wait()
        finally:
            running -= 1
            completed += 1

    svc._dispatch = blocking_dispatch

    dispatch_task = asyncio.create_task(svc.dispatch("test.topic", make_event()))

    # Two handlers reach their gate. Because acquire is synchronous when a permit is free,
    # the dispatch loop has already reached and blocked on the third acquire by the time both
    # handlers are running — no wall-clock sleep needed.
    await asyncio.wait_for(two_running.wait(), timeout=TEST_TIMEOUT)

    assert running == 2
    assert svc._dispatch_semaphore.locked()
    assert not dispatch_task.done(), "dispatch loop should block once the ceiling is hit"

    # Release: remaining handlers drain through the freed slots.
    gate.set()
    await asyncio.wait_for(dispatch_task, timeout=TEST_TIMEOUT)
    await svc.await_dispatch_idle(timeout=TEST_TIMEOUT)

    assert completed == 4
    assert peak == 2, "concurrency never exceeded the ceiling"
    assert not svc._dispatch_semaphore.locked(), "all slots released after drain"


async def test_dispatch_under_limit_runs_all_without_blocking() -> None:
    """Below the ceiling, every handler dispatches and the loop never blocks (behavior unchanged)."""
    svc = make_bus_service(max_concurrent_dispatches=10)
    register_listeners(svc, "test.topic", 3)

    seen = 0

    async def counting_dispatch(_route, _event, _listener) -> None:
        nonlocal seen
        seen += 1

    svc._dispatch = counting_dispatch

    await asyncio.wait_for(svc.dispatch("test.topic", make_event()), timeout=TEST_TIMEOUT)
    await svc.await_dispatch_idle(timeout=TEST_TIMEOUT)

    assert seen == 3
    assert not svc._dispatch_semaphore.locked()


async def test_slot_released_when_handler_raises() -> None:
    """A handler that raises still releases its slot — no permit leak."""
    svc = make_bus_service(max_concurrent_dispatches=2)
    register_listeners(svc, "test.topic", 2)

    async def failing_dispatch(_route, _event, _listener) -> None:
        raise RuntimeError("handler boom")

    svc._dispatch = failing_dispatch

    await asyncio.wait_for(svc.dispatch("test.topic", make_event()), timeout=TEST_TIMEOUT)
    await svc.await_dispatch_idle(timeout=TEST_TIMEOUT)

    await assert_all_slots_reacquirable(svc, 2)


async def test_slot_released_when_handler_cancelled() -> None:
    """A handler task cancelled mid-flight still releases its slot — done-callback fires on cancel."""
    svc = make_bus_service(max_concurrent_dispatches=2)
    register_listeners(svc, "test.topic", 2)

    gate = asyncio.Event()
    spawned: list[asyncio.Task] = []

    def capturing_spawn(coro, **_kw):
        task = asyncio.create_task(coro)
        spawned.append(task)
        return task

    svc.task_bucket.spawn = capturing_spawn

    async def hanging_dispatch(_route, _event, _listener) -> None:
        await gate.wait()  # never set — tasks are cancelled instead

    svc._dispatch = hanging_dispatch

    await asyncio.wait_for(svc.dispatch("test.topic", make_event()), timeout=TEST_TIMEOUT)
    assert svc._dispatch_semaphore.locked()  # both slots held by the hanging handlers

    # Cancel the in-flight handler tasks (as shutdown would).
    for task in spawned:
        task.cancel()
    await svc.await_dispatch_idle(timeout=TEST_TIMEOUT)

    # Both slots returned despite cancellation.
    await assert_all_slots_reacquirable(svc, 2)


async def test_saturation_warning_is_rate_limited() -> None:
    """Repeated saturation logs once per window, not once per blocked dispatch."""
    svc = make_bus_service(max_concurrent_dispatches=1)

    svc.warn_dispatch_saturated()
    svc.warn_dispatch_saturated()
    svc.warn_dispatch_saturated()

    assert svc.logger.warning.call_count == 1

    # Simulate the rate-limit window elapsing (push the last-warn timestamp past the window).
    svc._last_saturation_warn_ts -= _DISPATCH_SATURATION_WARN_RATE_LIMIT_SECS * 2
    svc.warn_dispatch_saturated()
    assert svc.logger.warning.call_count == 2
