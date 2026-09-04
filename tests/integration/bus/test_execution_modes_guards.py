"""Integration tests for execution-mode guard internals (design 073).

Covers the parts of the per-listener overlap-mode machinery that sit behind the public dispatch
behavior tested in ``test_execution_modes.py``: live-execution-count snapshots, persisted
backpressure policy, the stall watchdog, and queued ``pending_done`` draining on cancellation.
"""

import asyncio
import typing
import unittest.mock
from unittest.mock import AsyncMock, Mock

import pytest

import hassette.bus.listeners as bus_listeners_module
from hassette.core.bus_service import BusService
from hassette.core.command_executor import CommandExecutor
from hassette.core.database_service import DatabaseService
from hassette.events import RawStateChangeEvent
from hassette.schemas.live_counts import LiveCounts
from hassette.testing import wait_for
from tests.support.helpers import create_listener

from .helpers import ENTITY, fire, pump_event_loop, seed

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.bus import Bus
    from hassette.testing import HassetteHarness


async def test_live_execution_counts_snapshot_keyed_by_db_id(
    bus_harness: "tuple[HassetteHarness, Hassette, Bus]",
) -> None:
    """live_execution_counts() exposes per-listener (suppressed, dropped) keyed by db_id."""
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
    assert counts[db_id] == LiveCounts(suppressed=1, dropped=0, backpressure_dropped=0)

    gate.set()
    await harness.bus_service.await_dispatch_idle()


async def test_live_execution_counts_includes_backpressure_dropped(
    bus_harness: "tuple[HassetteHarness, Hassette, Bus]",
) -> None:
    """live_execution_counts() surfaces a listener's backpressure-drop counter by db_id."""
    harness, _hassette, bus = bus_harness
    await seed(harness, ENTITY, "0")

    async def handler(_event: RawStateChangeEvent) -> None:
        pass

    sub = await bus.on_state_change(ENTITY, handler=handler, name="counts_bp", backpressure="drop_newest")
    db_id = sub.listener.db_id
    assert db_id is not None

    # The gate increments invoker.backpressure_dropped under saturation (covered by backpressure unit tests);
    # here we set it directly to assert the snapshot reads the counter, not a hardcoded zero.
    sub.listener.invoker.backpressure_dropped = 3

    counts = harness.bus_service.live_execution_counts()
    assert counts[db_id] == LiveCounts(suppressed=0, dropped=0, backpressure_dropped=3)


async def test_live_execution_counts_omits_retired_listener(
    bus_harness: "tuple[HassetteHarness, Hassette, Bus]",
) -> None:
    """A cancelled (retired) listener drops out of the live snapshot; web maps it to 0."""
    harness, _hassette, bus = bus_harness
    await seed(harness, ENTITY, "0")

    async def handler(_event: RawStateChangeEvent) -> None:
        pass

    sub = await bus.on_state_change(ENTITY, handler=handler, name="counts_retired", mode="single")
    db_id = sub.listener.db_id
    assert db_id is not None
    assert db_id in harness.bus_service.live_execution_counts()

    sub.cancel()
    await pump_event_loop()

    assert db_id not in harness.bus_service.live_execution_counts()


@pytest.fixture
async def real_executor(
    db_hassette: AsyncMock,
    initialized_db: tuple[DatabaseService, int],  # noqa: ARG001
) -> CommandExecutor:
    """CommandExecutor wired to a real migrated DB — for persistence assertions."""
    exc = CommandExecutor(db_hassette, parent=db_hassette)
    await exc.on_initialize()
    return exc


async def test_backpressure_policy_persisted_on_registration(
    real_executor: CommandExecutor,
    initialized_db: tuple[DatabaseService, int],
    db_hassette: AsyncMock,
) -> None:
    """Persisted backpressure column matches the configured policy at registration time.

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
    """Re-registering with if_exists='replace' and a changed policy updates the persisted row.

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


async def test_stall_watchdog_emits_warning_for_non_parallel(
    bus_harness: "tuple[HassetteHarness, Hassette, Bus]",
) -> None:
    """A single/queued invocation held past the stall threshold emits a stall WARNING.

    Characterization pin for the dispatch-mode bridge extraction: this must pass against the
    current code and guard the later bus-migration change (shared with
    ``test_queued_trigger_pending_done_resolved_on_release`` below).

    Mirrors ``test_stall_watchdog_emits_warning_for_non_parallel`` in
    ``tests/integration/test_scheduler_mode.py``. Spies on
    ``HandlerInvoker.warn_stalled`` so a deleted ``call_later`` registration
    (which would still pass a "dispatch is still pending" check) fails the spy
    assertion — the robust check.

    Patch-target note: patches ``bus_listeners_module.STALL_THRESHOLD_SECONDS``
    (the module-level constant the ``call_later`` call reads) and spies on the
    class method via ``patch.object(bus_listeners_module.HandlerInvoker, "warn_stalled")``.
    Patching the wrong target leaves the watchdog armed at 60s and the spy
    never fires — yielding a false-green pin.

    Assertion: ``mock_warn.assert_called_once_with(0.05)`` — the patched threshold
    is passed to ``warn_stalled(threshold)`` by the shared ``run_with_stall_watch``
    helper.

    Timing note: the listener is registered OUTSIDE the patch block on purpose.
    The ``call_later`` arm runs inside ``run_with_stall_watch`` (in
    ``hassette.execution_mode``) — i.e. after ``fire()``, inside the ``with``
    block — so it captures ``self.warn_stalled`` after the mock is installed.
    Moving ``fire()`` outside the block would make the spy miss the call.
    """
    harness, _hassette, bus = bus_harness
    await seed(harness, ENTITY, "off")

    started = asyncio.Event()
    gate = asyncio.Event()

    async def handler(_event: RawStateChangeEvent) -> None:
        started.set()
        await gate.wait()

    await bus.on_state_change(
        ENTITY,
        handler=handler,
        name="stall_watch_pin",
        mode="single",
        timeout_disabled=True,
    )

    with (
        unittest.mock.patch.object(bus_listeners_module, "STALL_THRESHOLD_SECONDS", 0.05),
        unittest.mock.patch.object(bus_listeners_module.HandlerInvoker, "warn_stalled") as mock_warn,
    ):
        await fire(harness, "off", "on")
        await asyncio.wait_for(started.wait(), timeout=2.0)

        # Wait deterministically for the watchdog to fire (past the patched 0.05s
        # threshold) rather than sleeping a fixed interval and hoping.
        await wait_for(lambda: mock_warn.call_count >= 1)

        assert harness.bus_service.dispatch_pending_count > 0, (
            "Dispatch should still be pending (handler is blocking on gate)"
        )
        # Assert the watchdog actually fired — not just that the handler is still running.
        # warn_stalled(threshold) — threshold is passed by the shared run_with_stall_watch helper.
        mock_warn.assert_called_once_with(0.05)

    # Unblock and drain.
    gate.set()
    await harness.bus_service.await_dispatch_idle()


async def test_queued_trigger_pending_done_resolved_on_release(
    bus_harness: "tuple[HassetteHarness, Hassette, Bus]",
) -> None:
    """A QUEUED_ACCEPTED trigger's pending_done future resolves when the listener is released.

    Complements ``test_cancelling_queued_listener_releases_pending`` (in
    ``test_execution_modes.py``) with an explicit assertion that the ``pending_done`` set is empty
    after release — i.e. release_guard() drains the unresolved futures so outer dispatch tasks
    unwind rather than hanging.

    This pins the drain behaviour in ``HandlerInvoker.release_guard`` before the
    bus migration touches that method.
    """
    harness, _hassette, bus = bus_harness
    await seed(harness, ENTITY, "v0")

    first_started = asyncio.Event()
    release_first = asyncio.Event()

    async def handler(_event: RawStateChangeEvent) -> None:
        if not first_started.is_set():
            first_started.set()
            await release_first.wait()

    sub = await bus.on_state_change(
        ENTITY,
        handler=handler,
        name="queued_drain_pin",
        mode="queued",
    )

    await fire(harness, "v0", "a")  # starts the first handler — blocks on release_first
    await asyncio.wait_for(first_started.wait(), timeout=2.0)

    # Queue a second trigger while the first is running.
    await fire(harness, "a", "b")

    guard = sub.listener.invoker.guard
    await wait_for(lambda: len(guard.pending) >= 1)

    # Before release: both the running invocation and the queued trigger have
    # pending_done futures parked (non-parallel modes add one per invocation).
    assert len(sub.listener.invoker.pending_done) >= 2, (
        "pending_done must hold futures for both the running and queued invocations"
    )

    # Cancel/release the listener — must drain all pending_done futures.
    sub.cancel()
    await wait_for(lambda: len(guard.pending) == 0 and guard.current_task is None)

    # Unblock the (now cancelled) first invocation.
    release_first.set()
    await harness.bus_service.await_dispatch_idle()

    # The drain must have resolved every pending_done future — none should remain.
    assert len(sub.listener.invoker.pending_done) == 0, (
        "release_guard() must drain all pending_done futures so outer dispatch tasks unwind"
    )
