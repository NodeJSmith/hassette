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
import hassette.execution_mode as execution_mode_module
from hassette.core.bus_service import BusService
from hassette.core.command_executor import CommandExecutor
from hassette.core.database_service import DatabaseService
from hassette.events import RawStateChangeEvent
from hassette.schemas.live_counts import LiveCounts
from hassette.testing import wait_for
from hassette.types import Topic
from tests.support.helpers import HANG_GUARD_TIMEOUT_SECONDS, create_listener

from .helpers import ENTITY, fire, make_gated_handler, pump_event_loop, seed

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

    handler, record = make_gated_handler()

    sub = await bus.on_state_change(ENTITY, handler=handler, name="counts_single", mode="single")
    db_id = sub.listener.db_id
    assert db_id is not None  # the harness assigns a db_id at registration

    await fire(harness, "0", "1")  # starts and blocks
    await wait_for(lambda: record.started == 1)
    await fire(harness, "1", "2")  # suppressed re-fire
    await wait_for(lambda: sub.listener.invoker.guard.suppressed == 1)

    counts = harness.bus_service.live_execution_counts()
    assert counts[db_id] == LiveCounts(suppressed=1, dropped=0, backpressure_dropped=0)

    record.gate.set()
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
    ``tests/integration/test_scheduler_mode_dispatch_edge_cases.py``. Spies on
    ``HandlerInvoker.warn_stalled`` so a deleted ``call_later`` registration
    (which would still pass a "dispatch is still pending" check) fails the spy
    assertion — the robust check.

    Patch-target note: patches ``execution_mode_module.STALL_THRESHOLD_SECONDS``
    (the module-level constant ``stall_threshold`` reads) and spies on the
    class method via ``patch.object(bus_listeners_module.HandlerInvoker, "warn_stalled")``.
    Patching the wrong target leaves the watchdog armed at 60s and the spy
    never fires — yielding a false-green pin.

    Assertion: ``mock_warn.assert_called_once_with(0.05, None)`` — the patched threshold
    reaches ``warn_stalled`` through the shared ``run_with_stall_watch`` helper, and
    ``timeout_disabled=True`` leaves no effective timeout, so the default applies.

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
        unittest.mock.patch.object(execution_mode_module, "STALL_THRESHOLD_SECONDS", 0.05),
        unittest.mock.patch.object(bus_listeners_module.HandlerInvoker, "warn_stalled") as mock_warn,
    ):
        await fire(harness, "off", "on")
        await asyncio.wait_for(started.wait(), timeout=HANG_GUARD_TIMEOUT_SECONDS)

        # Wait deterministically for the watchdog to fire (past the patched 0.05s
        # threshold) rather than sleeping a fixed interval and hoping.
        await wait_for(lambda: mock_warn.call_count >= 1)

        assert harness.bus_service.dispatch_pending_count > 0, (
            "Dispatch should still be pending (handler is blocking on gate)"
        )
        # Assert the watchdog actually fired — not just that the handler is still running.
        mock_warn.assert_called_once_with(0.05, None)

    # Unblock and drain.
    gate.set()
    await harness.bus_service.await_dispatch_idle()


async def test_stall_threshold_derives_from_listener_timeout(
    bus_harness: "tuple[HassetteHarness, Hassette, Bus]",
) -> None:
    """A handler with its own timeout stays quiet past the default threshold and warns at 80% of the timeout."""
    harness, _hassette, bus = bus_harness
    await seed(harness, ENTITY, "off")

    started = asyncio.Event()
    gate = asyncio.Event()

    async def handler(_event: RawStateChangeEvent) -> None:
        started.set()
        await gate.wait()

    await bus.on_state_change(ENTITY, handler=handler, name="stall_derived", mode="single", timeout=0.5)

    # The patched default stands in for 60s, and timeout=0.5 stands in for a declared-slow handler.
    with (
        unittest.mock.patch.object(execution_mode_module, "STALL_THRESHOLD_SECONDS", 0.01),
        unittest.mock.patch.object(bus_listeners_module.HandlerInvoker, "warn_stalled") as mock_warn,
    ):
        await fire(harness, "off", "on")
        await asyncio.wait_for(started.wait(), timeout=HANG_GUARD_TIMEOUT_SECONDS)

        await asyncio.sleep(0.1)  # well past the default threshold, short of the derived one
        mock_warn.assert_not_called()

        await wait_for(lambda: mock_warn.call_count >= 1)
        mock_warn.assert_called_once_with(0.4, 0.5)

    gate.set()
    await harness.bus_service.await_dispatch_idle()


@pytest.mark.parametrize(
    ("registration", "expected_timeout"),
    [
        pytest.param({"timeout": 300.0}, lambda _config: 300.0, id="per_listener_timeout"),
        pytest.param({"timeout_disabled": True}, lambda _config: None, id="timeout_disabled"),
        pytest.param({}, lambda config: config.lifecycle.event_handler_timeout_seconds, id="global_default"),
    ],
)
async def test_stall_resolver_matches_enforced_timeout(
    bus_harness: "tuple[HassetteHarness, Hassette, Bus]",
    registration: dict[str, typing.Any],
    expected_timeout: typing.Callable[[typing.Any], float | None],
) -> None:
    """Dispatch gives the guard a resolver for the listener's effective timeout."""
    harness, hassette, bus = bus_harness
    await seed(harness, ENTITY, "off")

    fired = asyncio.Event()

    async def handler(_event: RawStateChangeEvent) -> None:
        fired.set()

    await bus.on_state_change(ENTITY, handler=handler, name="stall_threshold_arg", mode="single", **registration)

    with unittest.mock.patch.object(
        bus_listeners_module, "run_through_guard", wraps=bus_listeners_module.run_through_guard
    ) as spy:
        await fire(harness, "off", "on")
        await asyncio.wait_for(fired.wait(), timeout=HANG_GUARD_TIMEOUT_SECONDS)

    assert spy.call_args.kwargs["resolve_timeout"]() == expected_timeout(hassette.config)
    await harness.bus_service.await_dispatch_idle()


async def test_queued_stall_threshold_uses_timeout_at_start(
    bus_harness: "tuple[HassetteHarness, Hassette, Bus]",
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A config reload during a queue wait moves the watchdog along with the enforced timeout."""
    harness, hassette, bus = bus_harness
    await seed(harness, ENTITY, "0")
    monkeypatch.setattr(hassette.config.lifecycle, "event_handler_timeout_seconds", 30.0)

    first_gate = asyncio.Event()
    second_gate = asyncio.Event()
    starts = 0

    async def handler(_event: RawStateChangeEvent) -> None:
        nonlocal starts
        starts += 1
        if starts == 1:
            await first_gate.wait()
            return
        await second_gate.wait()

    await bus.on_state_change(ENTITY, handler=handler, name="stall_queued_reload", mode="queued")

    with (
        unittest.mock.patch.object(execution_mode_module, "STALL_THRESHOLD_SECONDS", 0.01),
        unittest.mock.patch.object(bus_listeners_module.HandlerInvoker, "warn_stalled") as mock_warn,
    ):
        await fire(harness, "0", "1")
        await wait_for(lambda: starts == 1)
        await fire(harness, "1", "2")  # queues behind the first

        # Before the reload, the queued invocation's threshold would be 24s, past any wait here.
        monkeypatch.setattr(hassette.config.lifecycle, "event_handler_timeout_seconds", 0.25)
        first_gate.set()

        await wait_for(lambda: mock_warn.call_count >= 1)
        mock_warn.assert_called_once_with(execution_mode_module.stall_threshold(0.25), 0.25)

    second_gate.set()
    await harness.bus_service.await_dispatch_idle()


async def test_debounced_stall_threshold_uses_timeout_at_fire(
    bus_harness: "tuple[HassetteHarness, Hassette, Bus]",
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A config reload during a debounce window moves the watchdog along with the enforced timeout."""
    harness, hassette, bus = bus_harness
    await seed(harness, ENTITY, "off")
    monkeypatch.setattr(hassette.config.lifecycle, "event_handler_timeout_seconds", 30.0)

    gate = asyncio.Event()

    async def handler(_event: RawStateChangeEvent) -> None:
        await gate.wait()

    await bus.on_state_change(ENTITY, handler=handler, name="stall_debounce_reload", mode="single", debounce=0.5)

    with (
        unittest.mock.patch.object(execution_mode_module, "STALL_THRESHOLD_SECONDS", 0.01),
        unittest.mock.patch.object(bus_listeners_module.HandlerInvoker, "warn_stalled") as mock_warn,
    ):
        await fire(harness, "off", "on")

        # The reload lands inside the debounce window, well before the handler starts.
        monkeypatch.setattr(hassette.config.lifecycle, "event_handler_timeout_seconds", 0.25)

        await wait_for(lambda: mock_warn.call_count >= 1)
        mock_warn.assert_called_once_with(execution_mode_module.stall_threshold(0.25), 0.25)

    gate.set()
    await harness.bus_service.await_dispatch_idle()


async def test_prebuilt_listener_stall_threshold_uses_global_timeout(
    bus_harness: "tuple[HassetteHarness, Hassette, Bus]",
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A listener built by hand and added through ``add_listener`` warns against the global timeout it runs under."""
    harness, hassette, bus = bus_harness
    await seed(harness, ENTITY, "off")
    monkeypatch.setattr(hassette.config.lifecycle, "event_handler_timeout_seconds", 0.5)

    started = asyncio.Event()
    gate = asyncio.Event()

    async def handler(_event: RawStateChangeEvent) -> None:
        started.set()
        await gate.wait()

    listener = create_listener(
        task_bucket=bus.task_bucket,
        handler=handler,
        owner_id=bus.owner_id,
        topic=f"{Topic.HASS_EVENT_STATE_CHANGED!s}.{ENTITY}",
        name="stall_prebuilt",
        mode="single",
    )
    await bus.add_listener(listener)

    with (
        unittest.mock.patch.object(execution_mode_module, "STALL_THRESHOLD_SECONDS", 0.01),
        unittest.mock.patch.object(bus_listeners_module.HandlerInvoker, "warn_stalled") as mock_warn,
    ):
        await fire(harness, "off", "on")
        await asyncio.wait_for(started.wait(), timeout=HANG_GUARD_TIMEOUT_SECONDS)

        await wait_for(lambda: mock_warn.call_count >= 1)
        mock_warn.assert_called_once_with(0.4, 0.5)

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
    await asyncio.wait_for(first_started.wait(), timeout=HANG_GUARD_TIMEOUT_SECONDS)

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


async def test_handler_cancelling_own_subscription_is_cancelled(
    bus_harness: "tuple[HassetteHarness, Hassette, Bus]",
) -> None:
    """A non-parallel handler that cancels its own subscription is cancelled mid-run.

    ``Listener.cancel()`` spawns ``release_guard()`` from the handler's context, so the release
    carries the invocation's context — it must still cancel the in-flight handler rather than
    detach it the way a scheduler job replacing itself is detached.
    """
    harness, _hassette, bus = bus_harness
    await seed(harness, ENTITY, "v0")

    subs: list = []
    never = asyncio.Event()
    handler_cancelled = asyncio.Event()

    async def handler(_event: RawStateChangeEvent) -> None:
        subs[0].cancel()
        try:
            await never.wait()
        except asyncio.CancelledError:
            handler_cancelled.set()
            raise

    subs.append(await bus.on_state_change(ENTITY, handler=handler, name="self_unsubscribe", mode="single"))

    await fire(harness, "v0", "a")

    await asyncio.wait_for(handler_cancelled.wait(), timeout=HANG_GUARD_TIMEOUT_SECONDS)
    await asyncio.wait_for(harness.bus_service.await_dispatch_idle(), timeout=HANG_GUARD_TIMEOUT_SECONDS)
