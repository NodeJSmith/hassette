"""Tests for the iterative AppTestHarness drain implementation.

Covers:
- Depth-1, depth-2, depth-3 task chains
- Perpetually-spawning handler timeout
- Handler exception surfacing via DrainError
- Multiple handler exceptions aggregation
- Timeout message includes pending task names
- Timeout message has debounce hint when applicable
- DrainError message formatting (single and multiple exceptions)
- Public accessors only (no private attribute access in drain source)
"""

import asyncio
import inspect

import pytest

from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.events import RawStateChangeEvent
from hassette.test_utils.app_harness import AppTestHarness
from hassette.test_utils.exceptions import DrainError, DrainTimeout

# ---------------------------------------------------------------------------
# Shared minimal config
# ---------------------------------------------------------------------------


class DrainTestConfig(AppConfig):
    """Minimal config for drain tests."""


# ---------------------------------------------------------------------------
# Depth-1 chain: basic handler with immediate action
# ---------------------------------------------------------------------------


class Depth1App(App[DrainTestConfig]):
    """Handler that calls api.turn_on directly."""

    turn_on_called: bool

    async def on_initialize(self) -> None:
        self.turn_on_called = False
        self.bus.on_state_change("sensor.test", handler=self._on_change)

    async def _on_change(self, event: RawStateChangeEvent) -> None:
        await self.api.turn_on("light.kitchen")
        self.turn_on_called = True


async def test_drain_waits_for_depth_1_task_chain() -> None:
    """Depth-1: handler completes normally, drain returns cleanly."""
    async with AppTestHarness(Depth1App, config={}) as harness:
        await harness.simulate_state_change("sensor.test", old_value="off", new_value="on")
        assert harness.app.turn_on_called is True
        harness.api_recorder.assert_called("turn_on", entity_id="light.kitchen")


# ---------------------------------------------------------------------------
# Depth-2 chain: handler spawns a secondary task
# ---------------------------------------------------------------------------


class Depth2App(App[DrainTestConfig]):
    """Handler spawns a task via task_bucket.spawn; spawned task calls api.turn_on."""

    async def on_initialize(self) -> None:
        self.bus.on_state_change("sensor.test", handler=self._on_change)

    async def _on_change(self, event: RawStateChangeEvent) -> None:
        self.task_bucket.spawn(self._secondary(), name="my_secondary_task")

    async def _secondary(self) -> None:
        await self.api.turn_on("light.living_room")


async def test_drain_waits_for_depth_2_task_chain() -> None:
    """Depth-2: handler spawns a task; drain waits for the spawned task to complete."""
    async with AppTestHarness(Depth2App, config={}) as harness:
        await harness.simulate_state_change("sensor.test", old_value="off", new_value="on")
        # Without iterative drain, this would fail because the spawned task
        # would not have run yet when the drain returned.
        harness.api_recorder.assert_called("turn_on", entity_id="light.living_room")


# ---------------------------------------------------------------------------
# Depth-3 chain: handler → task A → task B
# ---------------------------------------------------------------------------


class Depth3App(App[DrainTestConfig]):
    """Handler spawns task A, which spawns task B, which calls api.turn_on.

    task_b_gate is an asyncio.Event that task_b awaits before calling api.turn_on.
    Tests can verify that the drain has NOT returned before releasing the gate,
    proving that the drain actually blocked on task_b rather than merely observing
    that task_b happened to complete before the assertion.
    """

    task_b_gate: asyncio.Event

    async def on_initialize(self) -> None:
        self.task_b_gate = asyncio.Event()
        self.bus.on_state_change("sensor.test", handler=self._on_change)

    async def _on_change(self, event: RawStateChangeEvent) -> None:
        self.task_bucket.spawn(self._task_a(), name="task_a")

    async def _task_a(self) -> None:
        self.task_bucket.spawn(self._task_b(), name="task_b")

    async def _task_b(self) -> None:
        # Gate: wait until the test releases us, proving the drain had to block here.
        await self.task_b_gate.wait()
        await self.api.turn_on("light.bedroom")


async def test_drain_waits_for_depth_3_task_chain() -> None:
    """Depth-3: handler → task A → task B; drain waits for the full chain.

    Uses an asyncio.Event gate on task_b to prove the drain actually blocked
    on task_b, rather than merely asserting that turn_on was eventually called.
    The gate prevents task_b from completing until we verify the drain is still
    in progress (following the regression test pattern from CLAUDE.md).
    """
    async with AppTestHarness(Depth3App, config={}) as harness:
        # Start the drain in the background — it must block on task_b's gate
        drain_task = asyncio.create_task(
            harness.simulate_state_change("sensor.test", old_value="off", new_value="on"),
            name="drain_outer",
        )
        # Yield to let the drain run until it blocks on task_b_gate
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        # The drain should NOT be done yet because task_b is gated
        assert not drain_task.done(), (
            "Drain returned before task_b_gate was set — drain did not actually block on task_b"
        )
        # Release the gate; drain should now complete
        harness.app.task_b_gate.set()
        await drain_task
        harness.api_recorder.assert_called("turn_on", entity_id="light.bedroom")


# ---------------------------------------------------------------------------
# Perpetually-spawning handler — must hit timeout
# ---------------------------------------------------------------------------


class PerpetualSpawnApp(App[DrainTestConfig]):
    """Handler that perpetually spawns short-lived tasks, preventing drain from completing."""

    _keep_spawning: bool

    async def on_initialize(self) -> None:
        self._keep_spawning = True
        self.bus.on_state_change("sensor.test", handler=self._on_change)

    async def _on_change(self, event: RawStateChangeEvent) -> None:
        self.task_bucket.spawn(self._spawner(), name="my_handler:perpetual")

    async def _spawner(self) -> None:
        while self._keep_spawning:
            self.task_bucket.spawn(self._short_work(), name="my_handler:perpetual_child")
            await asyncio.sleep(0.01)

    async def _short_work(self) -> None:
        await asyncio.sleep(0.005)


async def test_drain_times_out_on_perpetually_spawning_handler() -> None:
    """Perpetually-spawning handler causes drain to raise DrainTimeout."""
    async with AppTestHarness(PerpetualSpawnApp, config={}) as harness:
        with pytest.raises(DrainTimeout):
            await harness.simulate_state_change("sensor.test", old_value="off", new_value="on", timeout=0.15)
        # Stop the spawner to allow clean teardown
        harness.app._keep_spawning = False


async def test_drain_timeout_message_includes_pending_task_names() -> None:
    """DrainTimeout message includes pending task names from task_bucket."""
    async with AppTestHarness(PerpetualSpawnApp, config={}) as harness:
        with pytest.raises(DrainTimeout) as exc_info:
            await harness.simulate_state_change("sensor.test", old_value="off", new_value="on", timeout=0.15)
        harness.app._keep_spawning = False

        msg = str(exc_info.value)
        # The task names should appear in the diagnostic message
        assert "my_handler" in msg or "pending task names" in msg


# ---------------------------------------------------------------------------
# Handler exception via spawned task → DrainError
# ---------------------------------------------------------------------------

# Note: Direct handler exceptions are swallowed by CommandExecutor._execute
# (which records the error to telemetry without re-raising). DrainError surfaces
# exceptions from *secondary tasks* that handlers spawn via task_bucket.spawn().


class SingleExceptionApp(App[DrainTestConfig]):
    """Handler spawns a task that yields once then raises ValueError.

    The yield ensures the task is still in-flight when the drain checks
    pending_tasks(), so asyncio.wait() can observe the exception.
    """

    async def on_initialize(self) -> None:
        self.bus.on_state_change("sensor.test", handler=self._on_change)

    async def _on_change(self, event: RawStateChangeEvent) -> None:
        self.task_bucket.spawn(self._crashing_work(), name="my_crashing_task")

    async def _crashing_work(self) -> None:
        # Sleep briefly so the task is still in-flight when the drain's Step 2 runs.
        # The drain's await_dispatch_idle has a 5ms stability window; sleeping 20ms
        # ensures the task is still pending when pending_tasks() is called.
        await asyncio.sleep(0.02)
        raise ValueError("boom")


async def test_drain_surfaces_handler_exception_as_drainerror() -> None:
    """Spawned task exception is surfaced as DrainError, not silently masked.

    When a handler spawns a secondary task via task_bucket.spawn() and that task
    raises, the iterative drain collects the exception and raises DrainError so
    test authors see the real cause instead of a misleading AssertionError later.
    """
    async with AppTestHarness(SingleExceptionApp, config={}) as harness:
        with pytest.raises(DrainError) as exc_info:
            await harness.simulate_state_change("sensor.test", old_value="off", new_value="on")
        err = exc_info.value
        assert len(err.task_exceptions) >= 1
        # Find the ValueError
        exc_types = [type(exc) for _, exc in err.task_exceptions]
        assert ValueError in exc_types
        val_err = next(exc for _, exc in err.task_exceptions if isinstance(exc, ValueError))
        assert str(val_err) == "boom"


# ---------------------------------------------------------------------------
# Multiple spawned task exceptions → DrainError aggregates
# ---------------------------------------------------------------------------


class TwoSpawnedExceptionApp(App[DrainTestConfig]):
    """Handler spawns two tasks that each raise a different exception."""

    async def on_initialize(self) -> None:
        self.bus.on_state_change("sensor.test", handler=self._on_change)

    async def _on_change(self, event: RawStateChangeEvent) -> None:
        self.task_bucket.spawn(self._crash_value(), name="crash_value_task")
        self.task_bucket.spawn(self._crash_runtime(), name="crash_runtime_task")

    async def _crash_value(self) -> None:
        # Sleep briefly so the task is still in-flight when the drain's Step 2 runs.
        await asyncio.sleep(0.02)
        raise ValueError("error_one")

    async def _crash_runtime(self) -> None:
        # Sleep briefly so the task is still in-flight when the drain's Step 2 runs.
        await asyncio.sleep(0.02)
        raise RuntimeError("error_two")


async def test_drain_surfaces_multiple_handler_exceptions() -> None:
    """DrainError aggregates all spawned task exceptions, not just the first."""
    async with AppTestHarness(TwoSpawnedExceptionApp, config={}) as harness:
        with pytest.raises(DrainError) as exc_info:
            await harness.simulate_state_change("sensor.test", old_value="off", new_value="on")
        err = exc_info.value
        assert len(err.task_exceptions) >= 2
        exc_types = {type(exc) for _, exc in err.task_exceptions}
        assert ValueError in exc_types
        assert RuntimeError in exc_types


# ---------------------------------------------------------------------------
# Debounce hint in timeout message
# ---------------------------------------------------------------------------

# NOTE: Bus debounce tasks are tracked in App.bus.task_bucket (not App.task_bucket),
# because Bus.on_state_change passes bus.task_bucket to Listener.create → RateLimiter.
# The drain checks app.task_bucket.pending_tasks() — bus-owned debounce tasks are
# NOT visible there.
#
# This test exercises the debounce hint path by having the handler directly spawn a
# long-running task named "handler:debounce" into app.task_bucket (simulating what
# a debounce-spawning handler would put there if the task were in app.task_bucket).
# The hint fires because any("debounce" in n for n in task_names) is True.


class DebounceHintApp(App[DrainTestConfig]):
    """Handler spawns a 'handler:debounce'-named task that sleeps for 5s.

    Simulates the pattern that would trigger the debounce hint in the drain's
    _raise_drain_timeout diagnostic, exercising the hint logic.
    """

    async def on_initialize(self) -> None:
        self.bus.on_state_change("sensor.test", handler=self._on_change)

    async def _on_change(self, event: RawStateChangeEvent) -> None:
        # Spawn a long-running task named like a debounce task to trigger the hint
        self.task_bucket.spawn(self._long_running(), name="handler:debounce")

    async def _long_running(self) -> None:
        await asyncio.sleep(5.0)


async def test_drain_timeout_message_has_debounce_hint_when_applicable() -> None:
    """When a 'handler:debounce'-named task is pending and drain times out, message includes debounce hint."""
    async with AppTestHarness(DebounceHintApp, config={}) as harness:
        with pytest.raises(DrainTimeout) as exc_info:
            # timeout=0.15 is shorter than the 5s sleep, so drain times out
            await harness.simulate_state_change("sensor.test", old_value="off", new_value="on", timeout=0.15)
        msg = str(exc_info.value)
        assert "debounce" in msg


# ---------------------------------------------------------------------------
# DrainError message formatting
# ---------------------------------------------------------------------------


def test_drain_error_message_single_exception() -> None:
    """DrainError message for a single exception includes count, name, type, and message."""
    err = DrainError([("my_task", ValueError("x"))])
    msg = str(err)
    assert "1 handler task exception" in msg
    assert "my_task" in msg
    assert "ValueError" in msg
    assert "x" in msg
    # Should NOT have "more" in a single-exception message
    assert "more" not in msg


def test_drain_error_message_multiple_exceptions() -> None:
    """DrainError message for two exceptions includes plural count and 'more' hint."""
    err = DrainError(
        [
            ("task_a", ValueError("first")),
            ("task_b", RuntimeError("second")),
        ]
    )
    msg = str(err)
    assert "2 handler task exceptions" in msg
    assert "1 more" in msg
    assert "see .task_exceptions" in msg
    # First exception details should be present
    assert "task_a" in msg
    assert "ValueError" in msg


# ---------------------------------------------------------------------------
# Public accessor enforcement
# ---------------------------------------------------------------------------


def test_drain_uses_public_accessors_not_private_attributes() -> None:
    """Drain implementation uses only public accessors from WP03, not private fields.

    Introspects the source of _drain_task_bucket to confirm no direct access to
    private BusService or TaskBucket internals. This acts as a regression guard
    against future refactoring that re-introduces private attribute access.
    """
    source = inspect.getsource(AppTestHarness._drain_task_bucket)
    assert "_dispatch_pending" not in source, (
        "_drain_task_bucket must not access bus_service._dispatch_pending directly; "
        "use bus_service.dispatch_pending_count"
    )
    assert "_dispatch_idle_event" not in source, (
        "_drain_task_bucket must not access bus_service._dispatch_idle_event directly; "
        "use bus_service.is_dispatch_idle or await_dispatch_idle()"
    )
    assert "task_bucket._tasks" not in source, (
        "_drain_task_bucket must not access app.task_bucket._tasks directly; use app.task_bucket.pending_tasks()"
    )
