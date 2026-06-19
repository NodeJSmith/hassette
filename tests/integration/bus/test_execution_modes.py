"""Integration tests for per-listener execution overlap modes (design 073).

Each mode is exercised through a real ``self.bus.on_state_change(...)`` registration against the
``bus_harness`` fixture (real bus, scheduler, state proxy). Handlers block on an ``asyncio.Event``
gate so re-fires arrive while a prior invocation is still running — the startup-race pattern from
CLAUDE.md. Suppressed/dropped drops are asserted via the live guard counters (per the testing
rules: assert the counter increment, not log capture).
"""

import asyncio
import typing
from unittest.mock import AsyncMock, Mock

import pytest

from hassette.core.bus_service import BusService, LiveCounts
from hassette.core.command_executor import CommandExecutor
from hassette.core.database_service import DatabaseService
from hassette.events import RawStateChangeEvent
from hassette.execution_mode import DEFAULT_QUEUE_DEPTH
from hassette.test_utils import wait_for
from hassette.test_utils.helpers import create_listener, create_state_change_event

from .helpers import seed

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.bus import Bus
    from hassette.test_utils.harness import HassetteHarness

ENTITY = "sensor.overlap"


async def fire(harness: "HassetteHarness", old: str, new: str) -> None:
    """Send one state-change event without waiting for dispatch to drain.

    A blocking handler keeps dispatch non-idle, so ``await_dispatch_idle`` cannot be used here.
    The event travels the stream → serve → dispatch → guard → child-task path, so callers wait on
    an explicit started-signal (``wait_for``) rather than this function before asserting.
    """
    event = create_state_change_event(entity_id=ENTITY, old_value=old, new_value=new)
    await harness.send_event(event)
    for _ in range(5):
        await asyncio.sleep(0)


async def test_single_runs_once_and_suppresses_refire(
    bus_harness: "tuple[HassetteHarness, Hassette, Bus]",
) -> None:
    """single yields exactly one execution on a double-fire; the second is suppressed (AC#3)."""
    harness, _hassette, bus = bus_harness
    await seed(harness, ENTITY, "0")

    started = 0
    gate = asyncio.Event()

    async def handler(_event: RawStateChangeEvent) -> None:
        nonlocal started
        started += 1
        await gate.wait()

    sub = await bus.on_state_change(ENTITY, handler=handler, name="single_mode", mode="single")

    await fire(harness, "0", "1")  # starts handler #1, which blocks on the gate
    await wait_for(lambda: started == 1)  # ensure #1 is running before the re-fire
    await fire(harness, "1", "2")  # re-fire while #1 is running -> suppressed
    await wait_for(lambda: sub.listener.invoker.guard.suppressed == 1)

    assert started == 1
    assert sub.listener.invoker.guard.suppressed == 1

    gate.set()
    await harness.bus_service.await_dispatch_idle()
    assert started == 1  # the suppressed re-fire never started a second invocation


async def test_restart_cancels_first_and_runs_second(
    bus_harness: "tuple[HassetteHarness, Hassette, Bus]",
) -> None:
    """restart cancels the running invocation and runs the new one; the bucket does not error (AC#4)."""
    harness, _hassette, bus = bus_harness
    await seed(harness, ENTITY, "0")

    started = 0
    cancelled = 0
    completed = 0
    gate = asyncio.Event()

    async def handler(_event: RawStateChangeEvent) -> None:
        nonlocal started, cancelled, completed
        started += 1
        try:
            await gate.wait()
            completed += 1
        except asyncio.CancelledError:
            cancelled += 1
            raise

    await bus.on_state_change(ENTITY, handler=handler, name="restart_mode", mode="restart")

    await fire(harness, "0", "1")  # starts #1, blocks
    await wait_for(lambda: started == 1)
    await fire(harness, "1", "2")  # cancels #1, starts #2
    await wait_for(lambda: started == 2 and cancelled == 1)

    assert started == 2
    assert cancelled == 1  # the first invocation observed CancelledError

    gate.set()
    await harness.bus_service.await_dispatch_idle()
    assert completed == 1  # only the second invocation completed


async def test_queued_runs_all_in_order(
    bus_harness: "tuple[HassetteHarness, Hassette, Bus]",
) -> None:
    """queued executes N triggers in arrival order after the first completes (AC#6)."""
    harness, _hassette, bus = bus_harness
    await seed(harness, ENTITY, "v0")

    order: list[str] = []
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    async def handler(event: RawStateChangeEvent) -> None:
        value = event.payload.data.new_state_value
        if not first_started.is_set():
            first_started.set()
            order.append(value)
            await release_first.wait()  # hold the first invocation so the rest queue behind it
            return
        order.append(value)

    sub = await bus.on_state_change(ENTITY, handler=handler, name="queued_mode", mode="queued")

    await fire(harness, "v0", "a")  # starts and blocks
    await first_started.wait()
    await fire(harness, "a", "b")  # queued
    await fire(harness, "b", "c")  # queued

    release_first.set()
    # await_dispatch_idle() must not return until every queued handler has actually run — the outer
    # dispatch task stays counted across the whole queue wait (no spin-loop needed).
    await harness.bus_service.await_dispatch_idle()

    assert order == ["a", "b", "c"]
    assert len(sub.listener.invoker.pending_done) == 0  # no completion futures left dangling


async def test_await_dispatch_idle_blocks_until_queued_handlers_run(
    bus_harness: "tuple[HassetteHarness, Hassette, Bus]",
) -> None:
    """await_dispatch_idle() must stay blocked while a queued handler is still pending (FIX 1).

    Regression for the _dispatch_pending undercount: a QUEUED_ACCEPTED trigger spawns its child only
    at drain time, so the outer dispatch task must remain counted across the queue wait. If it
    decrements early, await_dispatch_idle() returns while the second handler has not yet run.
    """
    harness, _hassette, bus = bus_harness
    await seed(harness, ENTITY, "v0")

    completed: list[str] = []
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    release_second = asyncio.Event()

    async def handler(event: RawStateChangeEvent) -> None:
        value = event.payload.data.new_state_value
        if not first_started.is_set():
            first_started.set()
            await release_first.wait()
            completed.append(value)
            return
        await release_second.wait()  # hold the queued (second) invocation open
        completed.append(value)

    await bus.on_state_change(ENTITY, handler=handler, name="queued_idle_gate", mode="queued")

    await fire(harness, "v0", "a")  # starts and blocks
    await first_started.wait()
    await fire(harness, "a", "b")  # queued behind the first

    idle_task = asyncio.create_task(harness.bus_service.await_dispatch_idle())

    # Let the first invocation finish and the queued one start, but keep the queued one blocked.
    release_first.set()
    await wait_for(lambda: completed == ["a"])
    for _ in range(5):
        await asyncio.sleep(0)
    assert not idle_task.done()  # still pending: the queued handler has not completed

    # Releasing the queued handler lets it finish — only now may await_dispatch_idle() return.
    release_second.set()
    await idle_task
    assert completed == ["a", "b"]


async def test_queued_cap_drops_newest(
    bus_harness: "tuple[HassetteHarness, Hassette, Bus]",
) -> None:
    """queued at cap drops the newest trigger, runs the rest, and counts the drop (AC#7)."""
    harness, _hassette, bus = bus_harness
    await seed(harness, ENTITY, "v0")

    completed: list[str] = []
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    async def handler(event: RawStateChangeEvent) -> None:
        value = event.payload.data.new_state_value
        if not first_started.is_set():
            first_started.set()
            await release_first.wait()
            completed.append(value)
            return
        completed.append(value)

    sub = await bus.on_state_change(ENTITY, handler=handler, name="queued_cap_mode", mode="queued")

    await fire(harness, "v0", "running")  # starts and blocks
    await first_started.wait()

    # Fill the queue to its cap, then one more that must be dropped (newest-dropped).
    prev = "running"
    for i in range(DEFAULT_QUEUE_DEPTH):
        nxt = f"q{i}"
        await fire(harness, prev, nxt)
        prev = nxt
    await fire(harness, prev, "overflow")  # at cap -> dropped

    assert sub.listener.invoker.guard.dropped == 1

    release_first.set()
    # await_dispatch_idle() waits for the first invocation and every drained queued one.
    await harness.bus_service.await_dispatch_idle()

    assert "overflow" not in completed
    # First invocation + DEFAULT_QUEUE_DEPTH queued ones all ran.
    assert len(completed) == DEFAULT_QUEUE_DEPTH + 1
    assert len(sub.listener.invoker.pending_done) == 0


async def test_live_execution_counts_snapshot_keyed_by_db_id(
    bus_harness: "tuple[HassetteHarness, Hassette, Bus]",
) -> None:
    """live_execution_counts() exposes per-listener (suppressed, dropped) by db_id (FR#15, AC#10)."""
    harness, _hassette, bus = bus_harness
    await seed(harness, ENTITY, "0")

    started = 0
    gate = asyncio.Event()

    async def handler(_event: RawStateChangeEvent) -> None:
        nonlocal started
        started += 1
        await gate.wait()

    sub = await bus.on_state_change(ENTITY, handler=handler, name="counts_single", mode="single")
    db_id = sub.listener.db_id
    assert db_id is not None  # the harness assigns a db_id at registration

    await fire(harness, "0", "1")  # starts and blocks
    await wait_for(lambda: started == 1)
    await fire(harness, "1", "2")  # suppressed re-fire
    await wait_for(lambda: sub.listener.invoker.guard.suppressed == 1)

    counts = harness.bus_service.live_execution_counts()
    assert counts[db_id] == LiveCounts(suppressed=1, dropped=0, bp_dropped=0)

    gate.set()
    await harness.bus_service.await_dispatch_idle()


async def test_live_execution_counts_includes_bp_dropped(
    bus_harness: "tuple[HassetteHarness, Hassette, Bus]",
) -> None:
    """live_execution_counts() surfaces a listener's backpressure-drop counter by db_id (FR#6)."""
    harness, _hassette, bus = bus_harness
    await seed(harness, ENTITY, "0")

    async def handler(_event: RawStateChangeEvent) -> None:
        pass

    sub = await bus.on_state_change(ENTITY, handler=handler, name="counts_bp", backpressure="drop_newest")
    db_id = sub.listener.db_id
    assert db_id is not None

    # The gate increments invoker.bp_dropped under saturation (covered by T02's unit tests);
    # here we set it directly to assert the snapshot reads the counter, not a hardcoded zero.
    sub.listener.invoker.bp_dropped = 3

    counts = harness.bus_service.live_execution_counts()
    assert counts[db_id] == LiveCounts(suppressed=0, dropped=0, bp_dropped=3)


async def test_live_execution_counts_omits_retired_listener(
    bus_harness: "tuple[HassetteHarness, Hassette, Bus]",
) -> None:
    """A cancelled (retired) listener drops out of the live snapshot; web maps it to 0 (FR#15)."""
    harness, _hassette, bus = bus_harness
    await seed(harness, ENTITY, "0")

    async def handler(_event: RawStateChangeEvent) -> None:
        pass

    sub = await bus.on_state_change(ENTITY, handler=handler, name="counts_retired", mode="single")
    db_id = sub.listener.db_id
    assert db_id is not None
    assert db_id in harness.bus_service.live_execution_counts()

    sub.cancel()
    for _ in range(5):
        await asyncio.sleep(0)

    assert db_id not in harness.bus_service.live_execution_counts()


async def test_parallel_runs_concurrently(
    bus_harness: "tuple[HassetteHarness, Hassette, Bus]",
) -> None:
    """parallel runs M triggers concurrently with no overlap guard (AC#8)."""
    harness, _hassette, bus = bus_harness
    await seed(harness, ENTITY, "0")

    concurrent = 0
    peak = 0
    gate = asyncio.Event()

    async def handler(_event: RawStateChangeEvent) -> None:
        nonlocal concurrent, peak
        concurrent += 1
        peak = max(peak, concurrent)
        try:
            await gate.wait()
        finally:
            concurrent -= 1

    await bus.on_state_change(ENTITY, handler=handler, name="parallel_mode", mode="parallel")

    await fire(harness, "0", "1")
    await fire(harness, "1", "2")
    await fire(harness, "2", "3")
    await wait_for(lambda: peak == 3)

    assert peak == 3  # all three ran concurrently — no overlap guard

    gate.set()
    await harness.bus_service.await_dispatch_idle()


async def test_invalid_mode_raises_at_registration(
    bus_harness: "tuple[HassetteHarness, Hassette, Bus]",
) -> None:
    """An invalid mode string is rejected at registration time (AC#9, FR#12)."""
    harness, _hassette, bus = bus_harness
    await seed(harness, ENTITY, "0")

    async def handler(_event: RawStateChangeEvent) -> None:
        pass

    with pytest.raises(ValueError, match="Invalid execution mode"):
        await bus.on_state_change(ENTITY, handler=handler, name="bad_mode", mode="nonsense")


async def test_cancelling_queued_listener_releases_pending(
    bus_harness: "tuple[HassetteHarness, Hassette, Bus]",
) -> None:
    """Cancelling a queued listener releases the in-flight task and drops queued factories (FR#17)."""
    harness, _hassette, bus = bus_harness
    await seed(harness, ENTITY, "v0")

    first_started = asyncio.Event()
    release_first = asyncio.Event()

    async def handler(_event: RawStateChangeEvent) -> None:
        if not first_started.is_set():
            first_started.set()
            await release_first.wait()

    sub = await bus.on_state_change(ENTITY, handler=handler, name="queued_release", mode="queued")

    await fire(harness, "v0", "a")  # starts and blocks
    await first_started.wait()
    await fire(harness, "a", "b")  # queued
    await fire(harness, "b", "c")  # queued

    guard = sub.listener.invoker.guard
    await wait_for(lambda: len(guard.pending) == 2)
    assert len(guard.pending) == 2

    # Cancelling the listener releases the guard: queue cleared, in-flight task cancelled.
    sub.cancel()
    await wait_for(lambda: len(guard.pending) == 0 and guard.current_task is None)

    assert len(guard.pending) == 0
    assert guard.current_task is None

    # Unblocking the (now cancelled) first invocation must not start the dropped queued factories.
    # release_guard() must resolve the parked completion futures for the dropped queued triggers, so
    # await_dispatch_idle() returns instead of hanging on outer dispatch tasks that never run.
    release_first.set()
    await harness.bus_service.await_dispatch_idle()
    assert len(sub.listener.invoker.pending_done) == 0  # released triggers leave no dangling futures


async def test_debounce_with_single_composes(
    bus_harness: "tuple[HassetteHarness, Hassette, Bus]",
) -> None:
    """debounce + mode='single' compose: debounce governs starts, single overlap of starts (AC#14)."""
    harness, _hassette, bus = bus_harness
    await seed(harness, ENTITY, "0")

    started = 0
    gate = asyncio.Event()

    async def handler(_event: RawStateChangeEvent) -> None:
        nonlocal started
        started += 1
        await gate.wait()

    await bus.on_state_change(ENTITY, handler=handler, name="debounce_single", mode="single", debounce=0.05)

    # Three rapid fires collapse to one debounced start. The single guard then governs overlap of
    # whatever started — here exactly one invocation begins after the quiet window.
    await fire(harness, "0", "1")
    await fire(harness, "1", "2")
    await fire(harness, "2", "3")
    await wait_for(lambda: started == 1)

    assert started == 1

    gate.set()
    await harness.bus_service.await_dispatch_idle()


async def test_once_with_non_single_mode_fires_at_most_once(
    bus_harness: "tuple[HassetteHarness, Hassette, Bus]",
) -> None:
    """A once=True handler fires at most once regardless of mode (AC#15, FR#21)."""
    harness, _hassette, bus = bus_harness
    await seed(harness, ENTITY, "0")

    started = 0

    async def handler(_event: RawStateChangeEvent) -> None:
        nonlocal started
        started += 1

    await bus.on_state_change(ENTITY, handler=handler, name="once_parallel", mode="parallel", once=True)

    await fire(harness, "0", "1")
    await harness.bus_service.await_dispatch_idle()
    await fire(harness, "1", "2")
    for _ in range(10):
        await asyncio.sleep(0)

    assert started == 1  # the once-guard runs before the mode guard


async def test_duration_hold_with_single_guards_at_expiry(
    bus_harness: "tuple[HassetteHarness, Hassette, Bus]",
) -> None:
    """A duration-hold handler with mode='single' applies the guard at hold-expiry dispatch (AC#16)."""
    harness, _hassette, bus = bus_harness
    await seed(harness, ENTITY, "off")

    started = 0
    gate = asyncio.Event()

    async def handler(_event: RawStateChangeEvent) -> None:
        nonlocal started
        started += 1
        await gate.wait()

    await bus.on_state_change(
        ENTITY,
        handler=handler,
        name="duration_single",
        mode="single",
        changed_to="on",
        duration=0.05,
    )

    # The handler does NOT start at trigger arrival — it starts only after the 50ms hold elapses.
    await fire(harness, "off", "on")
    assert started == 0  # guard is not applied at trigger arrival
    await wait_for(lambda: started == 1)

    assert started == 1  # the single guard applies at the delayed hold-expiry dispatch

    gate.set()
    await harness.bus_service.await_dispatch_idle()


async def test_framework_tier_listener_processes_concurrent_events(
    bus_harness: "tuple[HassetteHarness, Hassette, Bus]",
) -> None:
    """A framework-tier listener registered without ``mode`` defaults to parallel and runs concurrently.

    Guards the critical finding that the tier default must not constrain framework listeners — the
    supervisor must restart a second failed service while a first restart sleeps in backoff. Here a
    framework-tier subscription is exercised directly via the bus dispatch path (the system-level
    supervisor assertion requires Docker, unavailable in this suite — see task note).
    """
    harness, _hassette, bus = bus_harness
    await seed(harness, ENTITY, "0")

    # Substitute a mock parent reporting framework tier instead of mutating the live parent, so the
    # registration resolves to the framework default (mirrors test_source_tier_propagation.py).
    original_parent = bus.parent
    mock_parent = Mock()
    mock_parent.source_tier = "framework"
    mock_parent.app_key = original_parent.app_key
    mock_parent.index = original_parent.index
    mock_parent.unique_name = original_parent.unique_name
    mock_parent.class_name = original_parent.class_name
    bus.parent = mock_parent

    concurrent = 0
    peak = 0
    gate = asyncio.Event()

    async def handler(_event: RawStateChangeEvent) -> None:
        nonlocal concurrent, peak
        concurrent += 1
        peak = max(peak, concurrent)
        try:
            await gate.wait()
        finally:
            concurrent -= 1

    try:
        sub = await bus.on_state_change(ENTITY, handler=handler, name="framework_concurrent")
        # No explicit mode → framework tier resolves to parallel.
        assert sub.listener.options.mode.value == "parallel"

        await fire(harness, "0", "1")
        await fire(harness, "1", "2")
        await wait_for(lambda: peak == 2)

        assert peak == 2  # framework listeners are NOT serialized by the tier default

        gate.set()
        await harness.bus_service.await_dispatch_idle()
    finally:
        bus.parent = original_parent


@pytest.fixture
async def real_executor(db_hassette: AsyncMock, initialized_db: tuple[DatabaseService, int]) -> CommandExecutor:  # noqa: ARG001
    """CommandExecutor wired to a real migrated DB — for persistence assertions."""
    exc = CommandExecutor(db_hassette, parent=db_hassette)
    await exc.on_initialize()
    return exc


async def test_backpressure_policy_persisted_on_registration(
    real_executor: CommandExecutor,
    initialized_db: tuple[DatabaseService, int],
    db_hassette: AsyncMock,
) -> None:
    """AC#5: persisted backpressure column matches the configured policy at registration time.

    A DROP_NEWEST listener writes 'drop_newest'; a BLOCK/omitted listener writes 'block'.
    Uses a real CommandExecutor + migrated DB (bus_harness uses a mock executor with no DB).
    """
    db_service, _ = initialized_db
    stream = Mock()
    bus_service = BusService(db_hassette, stream=stream, executor=real_executor, parent=db_hassette)

    async def handler(event: object) -> None:
        pass

    drop_listener = create_listener(
        handler,
        topic="state_changed.sensor.power",
        app_key="test_app",
        instance_index=0,
        name="bp_test_drop_newest",
        backpressure="drop_newest",
    )
    reg_drop = bus_service.build_registration(drop_listener)
    await real_executor.register_listener(reg_drop)

    cursor = await db_service.db.execute(
        "SELECT backpressure FROM listeners WHERE name = ?",
        ("bp_test_drop_newest",),
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "drop_newest", f"Expected 'drop_newest', got {row[0]!r}"

    block_listener = create_listener(
        handler,
        topic="state_changed.sensor.power",
        app_key="test_app",
        instance_index=0,
        name="bp_test_block",
        backpressure="block",
    )
    reg_block = bus_service.build_registration(block_listener)
    await real_executor.register_listener(reg_block)

    cursor = await db_service.db.execute(
        "SELECT backpressure FROM listeners WHERE name = ?",
        ("bp_test_block",),
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "block", f"Expected 'block', got {row[0]!r}"


async def test_backpressure_policy_updated_on_replace_registration(
    real_executor: CommandExecutor,
    initialized_db: tuple[DatabaseService, int],
    db_hassette: AsyncMock,
) -> None:
    """AC#9: re-registering with if_exists='replace' and a changed policy updates the persisted row.

    Exercises the ON CONFLICT ... DO UPDATE SET backpressure = excluded.backpressure clause.
    Without that clause, the upsert would leave the old 'block' value in place.
    """
    db_service, _ = initialized_db
    stream = Mock()
    bus_service = BusService(db_hassette, stream=stream, executor=real_executor, parent=db_hassette)

    async def handler(event: object) -> None:
        pass

    first = create_listener(
        handler,
        topic="state_changed.sensor.replace_test",
        app_key="test_app",
        instance_index=0,
        name="bp_replace_test",
        backpressure="block",
    )
    reg_first = bus_service.build_registration(first)
    await real_executor.register_listener(reg_first)

    cursor = await db_service.db.execute(
        "SELECT backpressure FROM listeners WHERE name = ?",
        ("bp_replace_test",),
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "block"

    # Re-register with the same name + topic (triggers ON CONFLICT) but with DROP_NEWEST.
    second = create_listener(
        handler,
        topic="state_changed.sensor.replace_test",
        app_key="test_app",
        instance_index=0,
        name="bp_replace_test",
        backpressure="drop_newest",
    )
    reg_second = bus_service.build_registration(second)
    await real_executor.register_listener(reg_second)

    cursor = await db_service.db.execute(
        "SELECT backpressure FROM listeners WHERE name = ?",
        ("bp_replace_test",),
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "drop_newest", f"Expected 'drop_newest' after replace, got {row[0]!r}"
