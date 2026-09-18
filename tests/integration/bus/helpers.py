"""Shared helpers for bus integration tests."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from hassette.events import RawStateChangeEvent
from hassette.testing import HassetteHarness, create_state_change_event, make_state_dict, wait_for

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.bus import Bus

ENTITY = "sensor.overlap"
"""Shared entity id for execution-mode overlap tests (test_execution_modes*.py)."""

# Yielding to the event loop this many times lets a chain of already-scheduled callbacks
# (stream → serve → dispatch → guard → child-task spawn) all run without waiting on wall-clock
# time. Used where there is no completion signal to await on.
EVENT_LOOP_YIELDS = 10


async def seed(
    harness: HassetteHarness,
    entity_id: str,
    state_value: str,
    *,
    attributes: dict[str, Any] | None = None,
    last_changed: str | None = None,
) -> None:
    """Seed state into the StateProxy."""
    await harness.seed_state(
        entity_id,
        make_state_dict(entity_id, state_value, attributes=attributes, last_changed=last_changed),
    )


def make_collector(
    hassette: "Hassette",
) -> tuple[Callable[[RawStateChangeEvent], Awaitable[None]], list[RawStateChangeEvent], asyncio.Event]:
    """Build a handler that appends received events and signals completion via task_bucket.

    Returns ``(handler, received, fired)``. The handler appends every event it receives to
    ``received`` and sets ``fired`` (via ``hassette.task_bucket.post_to_loop``) each time it runs.
    Callers that don't need completion signaling — negative-fire tests gated on another wait
    condition — can discard ``fired`` with ``_fired``.
    """
    received: list[RawStateChangeEvent] = []
    fired = asyncio.Event()

    async def handler(event: RawStateChangeEvent) -> None:
        received.append(event)
        hassette.task_bucket.post_to_loop(fired.set)

    return handler, received, fired


@dataclass
class GatedHandlerRecord:
    """Bookkeeping for a handler built by ``make_gated_handler()``.

    ``gate`` blocks the handler until the test calls ``gate.set()``. ``completed`` increments
    whenever the gate resolves without cancellation, regardless of mode. ``cancelled`` is only
    populated for handlers registered with ``mode="restart"``, which observe
    ``asyncio.CancelledError`` while waiting on the gate — simpler callers (single/debounce/
    duration-hold tests) only ever read ``started``.
    """

    gate: asyncio.Event = field(default_factory=asyncio.Event)
    started: int = 0
    cancelled: int = 0
    completed: int = 0


def make_gated_handler() -> tuple[Callable[[RawStateChangeEvent], Awaitable[None]], GatedHandlerRecord]:
    """Build a handler that counts starts and blocks on an internal gate until released.

    Returns ``(handler, record)``. Each invocation increments ``record.started`` and then awaits
    ``record.gate`` (call ``record.gate.set()`` to release it). If the invocation is cancelled
    while waiting — the ``mode="restart"`` case — ``record.cancelled`` is incremented and the
    exception re-raised; otherwise ``record.completed`` is incremented once the gate opens.

    Covers the ``single``/``debounce``/``counts_single``/``duration_single``/``restart`` gated
    started-counter shape. Does not fit the concurrency-peak shape (``parallel``/framework-tier
    concurrent dispatch), which tracks a live count with a ``finally``-block decrement instead —
    use ``make_gated_concurrency_handler()`` there.
    """
    record = GatedHandlerRecord()

    async def handler(_event: RawStateChangeEvent) -> None:
        record.started += 1
        try:
            await record.gate.wait()
            record.completed += 1
        except asyncio.CancelledError:
            record.cancelled += 1
            raise

    return handler, record


@dataclass
class ConcurrencyRecord:
    """Bookkeeping for a handler built by ``make_gated_concurrency_handler()``.

    ``gate`` blocks every concurrent invocation until the test calls ``gate.set()``. ``concurrent``
    is the live in-flight count; ``peak`` is the highest value ``concurrent`` reached.
    """

    gate: asyncio.Event = field(default_factory=asyncio.Event)
    concurrent: int = 0
    peak: int = 0


def make_gated_concurrency_handler() -> tuple[Callable[[RawStateChangeEvent], Awaitable[None]], ConcurrencyRecord]:
    """Build a handler that tracks concurrent in-flight invocations against a shared gate.

    Returns ``(handler, record)``. Each invocation increments ``record.concurrent``, updates
    ``record.peak`` to the new high-water mark, then awaits ``record.gate`` and decrements
    ``record.concurrent`` in a ``finally`` block regardless of how the wait ends.

    Covers the ``parallel`` and framework-tier concurrent-dispatch shape. Does not fit the gated
    started-counter shape (single/debounce/duration/restart tests) — use ``make_gated_handler()``
    there.
    """
    record = ConcurrencyRecord()

    async def handler(_event: RawStateChangeEvent) -> None:
        record.concurrent += 1
        record.peak = max(record.peak, record.concurrent)
        try:
            await record.gate.wait()
        finally:
            record.concurrent -= 1

    return handler, record


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


async def drive_state_change(
    harness: HassetteHarness,
    entity_id: str,
    old_value: str,
    new_value: str,
) -> None:
    """Dispatch a state-change event, then sync StateProxy's cache to match.

    Combines ``send_state_change`` (drives the event through the bus, triggering listener
    dispatch) with ``seed`` (updates StateProxy's cached snapshot to the same new value) — dispatch
    and the state cache are updated independently by this harness, so any assertion or re-check
    logic that reads current state (duration-timer re-verification, ``get_state`` calls) needs
    both. Only fits the common case where both calls target the same entity/new-value pair; a test
    that seeds a different value than it dispatched, or needs other work between the two calls,
    should call ``send_state_change``/``seed`` directly instead.
    """
    await send_state_change(harness, entity_id, old_value, new_value)
    await seed(harness, entity_id, new_value)


async def send_live_event_and_wait_drain(
    hassette: "Hassette",
    bus: "Bus",
    entity_id: str,
    old_value: str,
    new_value: str,
) -> None:
    """Send a state-change event and wait for ``bus.task_bucket`` to drain.

    Used by ``once=True`` tests that prove a second live event does not re-fire an
    already-consumed listener — unlike ``drive_state_change``, the assertion that follows only
    cares whether the handler ran again, so this doesn't sync StateProxy's cache, and it waits on
    ``bus.task_bucket`` draining rather than ``bus_service.await_dispatch_idle()``, matching what
    each of these call sites already did before extraction.
    """
    event = create_state_change_event(entity_id=entity_id, old_value=old_value, new_value=new_value)
    await hassette.send_event(event)
    await wait_for(lambda: len(bus.task_bucket) == 0, desc="tasks drain")


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
