"""Integration tests for ServiceWatcher restart logic.

Tests use RestartSpec-based per-service configuration rather than global config fields.
"""

import asyncio
import time
from typing import ClassVar, NamedTuple
from unittest.mock import patch

import pytest

from hassette.core.service_watcher import ServiceWatcher
from hassette.events import Event, HassetteServiceEvent
from hassette.events.base import HassettePayload
from hassette.events.hassette import ServiceStatusPayload
from hassette.resources.lifecycle import mark_ready
from hassette.resources.restart import RestartSpec
from hassette.resources.service import Service
from hassette.test_utils import (
    EventCapture,
    make_service_failed_event,
    make_service_running_event,
    preserve_config,
    wait_for,
)
from hassette.test_utils.reset import reset_hassette_lifecycle
from hassette.types import ResourceStatus, Topic
from hassette.types.enums import RestartType

AWAIT_TIMEOUT = 5.0


def make_call_counts() -> dict[str, int]:
    """Fresh cancel/start counters for get_dummy_service."""
    return {"cancel": 0, "start": 0}


def make_fast_spec(**overrides: object) -> RestartSpec:
    """RestartSpec with zero backoff for test speed. Override any field via kwargs."""
    defaults: dict[str, object] = {"backoff_base_seconds": 0}
    defaults.update(overrides)
    return RestartSpec(**defaults)  # pyright: ignore[reportCallIssue]


@pytest.fixture
async def watcher(hassette_with_bus):
    """Return a fresh service watcher for each test."""
    hassette = hassette_with_bus.hassette
    watcher = ServiceWatcher(hassette, parent=hassette)
    original_children = list(hassette.children)
    with preserve_config(hassette.config):
        yield watcher
        # Clean up bus listeners registered by this watcher via propagation
        await watcher.shutdown()
        await reset_hassette_lifecycle(hassette, original_children=original_children)


async def restart_and_await(watcher: ServiceWatcher, event: HassetteServiceEvent) -> None:
    """Call restart_service and wait for the spawned execute_restart task to complete.

    restart_service now spawns the backoff+restart as a detached task and returns
    immediately. Tests that call restart_service sequentially need to wait for the
    in-restart flag to clear before the next call.
    """
    key = watcher.service_key(event.payload.data.resource_name, event.payload.data.role)
    was_restarting = key in watcher._restarting
    await watcher.restart_service(event)
    if not was_restarting and key in watcher._restarting:
        await wait_for(
            lambda: key not in watcher._restarting,
            desc=f"execute_restart for {key} completed",
            timeout=AWAIT_TIMEOUT,
        )


async def on_running_and_await(watcher: ServiceWatcher, event: HassetteServiceEvent) -> None:
    """Call on_service_running and wait for the spawned readiness task to complete."""
    pending_before = set(watcher.task_bucket.pending_tasks())
    await watcher.on_service_running(event)
    new_tasks = set(watcher.task_bucket.pending_tasks()) - pending_before
    for task in new_tasks:
        await asyncio.wait_for(asyncio.shield(task), timeout=AWAIT_TIMEOUT)


def get_dummy_service(
    called: dict[str, int],
    hassette,
    *,
    fail: bool = False,
    restart_spec: RestartSpec | None = None,
) -> Service:
    spec = restart_spec if restart_spec is not None else RestartSpec()

    class _Dummy(Service):
        """Does nothing, just tracks calls."""

        restart_spec: ClassVar[RestartSpec] = spec

        async def serve(self):
            await asyncio.Event().wait()

        async def on_shutdown(self):
            called["cancel"] += 1

        async def on_initialize(self):
            called["start"] += 1
            if fail:
                raise RuntimeError("always fails")

    return _Dummy(hassette)


class DummyServiceSetup(NamedTuple):
    """Everything a ServiceWatcher test needs to drive one dummy service."""

    service: Service
    calls: dict[str, int]
    spec: RestartSpec
    key: str
    failed_event: HassetteServiceEvent


def register_dummy_service(
    watcher: ServiceWatcher, *, fail: bool = False, **spec_overrides: object
) -> DummyServiceSetup:
    """Attach a dummy service to `watcher`'s hassette and pre-build what tests assert against."""
    calls = make_call_counts()
    spec = make_fast_spec(**spec_overrides)
    service = get_dummy_service(calls, watcher.hassette, fail=fail, restart_spec=spec)
    watcher.hassette.children.append(service)
    return DummyServiceSetup(
        service=service,
        calls=calls,
        spec=spec,
        key=watcher.service_key(service.class_name, service.role),
        failed_event=make_service_failed_event(service),
    )


async def exhaust_budget(watcher: ServiceWatcher, dummy: DummyServiceSetup, restarts: int) -> list[Event]:
    """Use up `restarts` budget slots, then fire the FAILED event that exhausts the budget.

    Returns the events emitted by that final, over-budget pass — the CRASHED / EXHAUSTED_COOLING
    / EXHAUSTED_DEAD event whose shape is what each restart type's test asserts on.
    """
    for _ in range(restarts):
        await restart_and_await(watcher, dummy.failed_event)

    with EventCapture.capturing(watcher.hassette) as capture:
        await watcher.restart_service(dummy.failed_event)

    return capture.events


def budget_entries(watcher: ServiceWatcher, key: str) -> int:
    """Count the live (non-expired) restart-budget entries recorded for `key`."""
    budget = watcher._budgets.get(key)
    assert budget is not None, f"No restart budget recorded for {key}"
    budget.evict_expired()
    return len(budget._timestamps)


async def test_restart_service_cancels_then_starts(watcher: ServiceWatcher):
    """Restarting a failed service cancels and reinitializes it."""
    dummy = register_dummy_service(watcher, restart_type=RestartType.TRANSIENT, budget_intensity=5)

    await watcher.restart_service(dummy.failed_event)

    await wait_for(
        lambda: dummy.calls == {"cancel": 1, "start": 1},
        desc="restart_service completed",
    )

    assert dummy.calls == {"cancel": 1, "start": 1}, (
        f"Expected cancel and start to be called once each, got {dummy.calls}"
    )


async def test_always_failing_service_stops_after_max_attempts(watcher: ServiceWatcher):
    """A service that always fails on restart stops being restarted after budget exhaustion."""
    hassette = watcher.hassette

    # budget_intensity=3 means 3 restarts before exhaustion
    dummy = register_dummy_service(watcher, fail=True, restart_type=RestartType.PERMANENT, budget_intensity=3)

    # Each call to restart_service increments budget and spawns a restart task.
    # The service fails on restart but exceptions are caught.
    for _ in range(3):
        await restart_and_await(watcher, dummy.failed_event)

    assert budget_entries(watcher, dummy.key) == 3
    assert not hassette.shutdown_event.is_set(), "Shutdown should not happen before budget exhausted"

    # The 4th call should trigger shutdown (budget exhausted, PERMANENT)
    await watcher.restart_service(dummy.failed_event)

    assert hassette.shutdown_event.is_set(), "Shutdown should be triggered after budget exhausted"


async def test_crashed_event_emitted_before_shutdown(watcher: ServiceWatcher):
    """When budget is exhausted for PERMANENT service, a CRASHED event is emitted before shutdown."""
    dummy = register_dummy_service(watcher, fail=True, restart_type=RestartType.PERMANENT, budget_intensity=1)

    # The one budget slot is used first, so the second call exceeds it
    events = await exhaust_budget(watcher, dummy, restarts=1)

    # First send_event call should be the CRASHED event (shutdown may emit STOPPED after)
    assert len(events) >= 1
    crashed_event = events[0]
    assert crashed_event.topic == Topic.HASSETTE_EVENT_SERVICE_STATUS
    assert crashed_event.payload.data.status == ResourceStatus.CRASHED
    assert crashed_event.payload.data.previous_status == ResourceStatus.FAILED
    assert crashed_event.payload.data.resource_name == dummy.service.class_name


async def test_exponential_backoff(watcher: ServiceWatcher):
    """Backoff delay increases exponentially between restart attempts (using shutdown-safe sleep)."""
    dummy = register_dummy_service(
        watcher,
        fail=True,
        restart_type=RestartType.TRANSIENT,
        budget_intensity=10,
        backoff_base_seconds=1.0,
        backoff_multiplier=2.0,
        backoff_max_seconds=60.0,
    )

    sleep_calls: list[float] = []

    async def mock_shutdown_safe_sleep(duration: float) -> bool:
        sleep_calls.append(duration)
        return True  # sleep completed normally

    with patch.object(watcher, "shutdown_safe_sleep", side_effect=mock_shutdown_safe_sleep):
        for _ in range(3):
            await restart_and_await(watcher, dummy.failed_event)

    # attempt 1: backoff = 1.0 * 2^0 = 1.0
    # attempt 2: backoff = 1.0 * 2^1 = 2.0
    # attempt 3: backoff = 1.0 * 2^2 = 4.0
    assert sleep_calls == [1.0, 2.0, 4.0]


async def test_budget_reset_on_recovery(watcher: ServiceWatcher):
    """Budget resets when a service transitions to RUNNING and becomes ready."""
    dummy = register_dummy_service(
        watcher, fail=True, restart_type=RestartType.TRANSIENT, budget_intensity=5, startup_timeout_seconds=1.0
    )

    # Accumulate 2 restart attempts
    for _ in range(2):
        await restart_and_await(watcher, dummy.failed_event)

    assert budget_entries(watcher, dummy.key) == 2

    # Mark the service ready, then fire RUNNING event — budget should reset
    mark_ready(dummy.service, reason="test")
    await on_running_and_await(watcher, make_service_running_event(dummy.service))

    assert budget_entries(watcher, dummy.key) == 0  # budget reset


async def test_permanent_exhaustion_triggers_shutdown(watcher: ServiceWatcher):
    """PERMANENT service: exhausting budget triggers hassette.shutdown()."""
    hassette = watcher.hassette
    dummy = register_dummy_service(watcher, restart_type=RestartType.PERMANENT, budget_intensity=2)

    # Use up budget
    await restart_and_await(watcher, dummy.failed_event)
    await restart_and_await(watcher, dummy.failed_event)

    assert not hassette.shutdown_event.is_set(), "Should not shutdown until budget exhausted"

    # Exhaust budget (budget check is synchronous — no spawn needed)
    await watcher.restart_service(dummy.failed_event)
    assert hassette.shutdown_event.is_set()


async def test_permanent_exhaustion_records_fatal_reason(watcher: ServiceWatcher):
    """PERMANENT exhaustion records _fatal_shutdown_reason synchronously at the decision site.

    Regression test for the reason-race: the CRASHED event is dispatched asynchronously
    (task-per-handler), so the reason must be set synchronously in handle_exhaustion — not
    only in the async shutdown_if_crashed handler — or run_forever() exits 0 on a real crash.
    """
    hassette = watcher.hassette
    assert hassette._fatal_shutdown_reason is None

    dummy = register_dummy_service(watcher, restart_type=RestartType.PERMANENT, budget_intensity=2)

    await restart_and_await(watcher, dummy.failed_event)
    await restart_and_await(watcher, dummy.failed_event)
    await watcher.restart_service(dummy.failed_event)  # exhausts → handle_exhaustion (PERMANENT, no spawn)

    assert hassette._fatal_shutdown_reason is not None
    assert dummy.service.class_name in hassette._fatal_shutdown_reason


async def test_fatal_error_records_fatal_reason(watcher: ServiceWatcher):
    """A service raising a configured fatal error records _fatal_shutdown_reason synchronously."""
    hassette = watcher.hassette
    assert hassette._fatal_shutdown_reason is None

    dummy = register_dummy_service(
        watcher,
        restart_type=RestartType.TRANSIENT,
        budget_intensity=5,
        fatal_error_names=("RuntimeError",),
    )

    event = make_service_failed_event(dummy.service, exception=RuntimeError("boom"))
    await watcher.restart_service(event)  # fatal-error path triggers immediately

    assert hassette._fatal_shutdown_reason is not None
    assert "RuntimeError" in hassette._fatal_shutdown_reason


async def test_transient_exhaustion_enters_cooldown(watcher: ServiceWatcher):
    """TRANSIENT service: exhausting budget emits EXHAUSTED_COOLING and schedules cooldown task."""
    hassette = watcher.hassette
    dummy = register_dummy_service(
        watcher,
        restart_type=RestartType.TRANSIENT,
        budget_intensity=2,
        cooldown_seconds=999,  # long cooldown so we can verify the task is created
    )

    events = await exhaust_budget(watcher, dummy, restarts=2)

    assert not hassette.shutdown_event.is_set(), "TRANSIENT exhaustion should NOT trigger shutdown"
    assert len(events) >= 1
    cooling_event = events[0]
    assert cooling_event.payload.data.status == ResourceStatus.EXHAUSTED_COOLING
    assert cooling_event.payload.data.retry_at is not None
    assert cooling_event.payload.data.retry_at > time.time()

    # Cooldown task should be scheduled
    assert dummy.key in watcher._cooldown_tasks
    assert not watcher._cooldown_tasks[dummy.key].done()

    # Cancel the cooldown task to avoid lingering
    watcher._cooldown_tasks[dummy.key].cancel()


async def test_temporary_exhaustion_stays_dead(watcher: ServiceWatcher):
    """TEMPORARY service: exhausting budget emits EXHAUSTED_DEAD, no further restarts."""
    hassette = watcher.hassette
    dummy = register_dummy_service(watcher, restart_type=RestartType.TEMPORARY, budget_intensity=2)

    events = await exhaust_budget(watcher, dummy, restarts=2)

    assert not hassette.shutdown_event.is_set()
    assert len(events) == 1
    dead_event = events[0]
    assert dead_event.payload.data.status == ResourceStatus.EXHAUSTED_DEAD
    assert dead_event.payload.data.retry_at is None


async def test_fatal_error_triggers_immediate_shutdown(watcher: ServiceWatcher):
    """Service with fatal_error_names: matching exception triggers immediate shutdown, no restart."""
    hassette = watcher.hassette
    dummy = register_dummy_service(
        watcher,
        restart_type=RestartType.TRANSIENT,
        fatal_error_names=("FatalDbError", "SchemaVersionError"),
        budget_intensity=5,
    )

    # Create a failed event with exception_type matching a fatal error name
    fatal_event = HassetteServiceEvent(
        topic=Topic.HASSETTE_EVENT_SERVICE_STATUS,
        payload=HassettePayload(
            data=ServiceStatusPayload(
                resource_name=dummy.service.class_name,
                role=dummy.service.role,
                status=ResourceStatus.FAILED,
                previous_status=ResourceStatus.RUNNING,
                exception="fatal db error",
                exception_type="FatalDbError",
                exception_traceback=None,
                ready=False,
                ready_phase=None,
            ),
        ),
    )

    with EventCapture.capturing(hassette) as capture:
        await watcher.restart_service(fatal_event)

    # Should have emitted CRASHED and triggered shutdown
    assert hassette.shutdown_event.is_set()
    assert len(capture.events) >= 1
    # First event should be CRASHED
    assert capture.events[0].payload.data.status == ResourceStatus.CRASHED
    # No restart should have been attempted
    assert dummy.calls["start"] == 0


async def test_non_retryable_error_skips_restart(watcher: ServiceWatcher):
    """Service with non_retryable_error_names: matching exception skips restart, goes to exhaustion."""
    hassette = watcher.hassette
    dummy = register_dummy_service(
        watcher,
        restart_type=RestartType.TEMPORARY,
        non_retryable_error_names=("NonRetryableError",),
        budget_intensity=5,
    )

    nr_event = HassetteServiceEvent(
        topic=Topic.HASSETTE_EVENT_SERVICE_STATUS,
        payload=HassettePayload(
            data=ServiceStatusPayload(
                resource_name=dummy.service.class_name,
                role=dummy.service.role,
                status=ResourceStatus.FAILED,
                previous_status=ResourceStatus.RUNNING,
                exception="non-retryable",
                exception_type="NonRetryableError",
                ready=False,
                ready_phase=None,
            ),
        ),
    )

    with EventCapture.capturing(hassette) as capture:
        await watcher.restart_service(nr_event)

    # No restart attempt made
    assert dummy.calls["start"] == 0
    # TEMPORARY exhaustion → EXHAUSTED_DEAD emitted
    assert len(capture.events) == 1
    assert capture.events[0].payload.data.status == ResourceStatus.EXHAUSTED_DEAD


async def test_in_restart_guard_prevents_double_budget(watcher: ServiceWatcher):
    """Two FAILED events while restart is in progress only record one budget entry."""
    dummy = register_dummy_service(watcher, restart_type=RestartType.TRANSIENT, budget_intensity=10)

    # Manually set the in-restart flag to simulate concurrent restart in progress
    watcher._restarting.add(dummy.key)
    # Ensure budget exists but has 1 entry (from the first restart)
    watcher.get_budget(dummy.key, dummy.spec).record_restart()

    # Second FAILED event arrives while restart is in progress — should be dropped
    await watcher.restart_service(dummy.failed_event)

    # Budget should still have only 1 entry
    assert budget_entries(watcher, dummy.key) == 1, "Second FAILED event should have been dropped by in-restart guard"

    # Clean up
    watcher._restarting.discard(dummy.key)


async def test_shutdown_safe_sleep_aborts_on_shutdown(watcher: ServiceWatcher):
    """Backoff sleep aborts early when shutdown_event is set."""
    hassette = watcher.hassette
    dummy = register_dummy_service(
        watcher,
        restart_type=RestartType.TRANSIENT,
        budget_intensity=10,
        backoff_base_seconds=5.0,  # real backoff that would be interrupted
        backoff_multiplier=1.0,
    )

    # Set shutdown event to trigger early abort during backoff
    hassette.shutdown_event.set()

    await restart_and_await(watcher, dummy.failed_event)

    # Service should NOT have been restarted
    assert dummy.calls["start"] == 0, "Service should not restart when shutdown is requested during backoff"
    # In-restart flag should be cleared
    assert dummy.key not in watcher._restarting


async def test_budget_reset_on_recovery_confirmed(watcher: ServiceWatcher):
    """Budget resets when service reaches RUNNING and signals readiness."""
    dummy = register_dummy_service(
        watcher, fail=True, restart_type=RestartType.TRANSIENT, budget_intensity=5, startup_timeout_seconds=1.0
    )

    # Accumulate 2 restart attempts
    await restart_and_await(watcher, dummy.failed_event)
    await restart_and_await(watcher, dummy.failed_event)

    assert budget_entries(watcher, dummy.key) == 2

    # Mark the service ready, then fire RUNNING event — budget should reset
    mark_ready(dummy.service, reason="test")
    await on_running_and_await(watcher, make_service_running_event(dummy.service))

    assert budget_entries(watcher, dummy.key) == 0  # budget.reset() was called
    assert dummy.key not in watcher._restarting  # in-restart cleared


async def test_readiness_timeout_no_budget_impact(watcher: ServiceWatcher):
    """Readiness timeout after RUNNING does NOT increment restart budget."""
    dummy = register_dummy_service(
        watcher, fail=True, restart_type=RestartType.TRANSIENT, budget_intensity=5, startup_timeout_seconds=0.05
    )

    # Accumulate 1 restart attempt
    await restart_and_await(watcher, dummy.failed_event)

    count_before = budget_entries(watcher, dummy.key)

    # Fire RUNNING event WITHOUT marking ready — timeout will occur, no budget impact
    # on_service_running spawns a readiness task; wait for it to time out
    await watcher.on_service_running(make_service_running_event(dummy.service))
    await wait_for(
        lambda: watcher.task_bucket.pending_tasks() == [],
        desc="readiness timeout task completed",
        timeout=AWAIT_TIMEOUT,
    )

    assert budget_entries(watcher, dummy.key) == count_before, "Readiness timeout should not impact restart budget"


async def test_cooldown_then_recovery(watcher: ServiceWatcher):
    """TRANSIENT exhaustion → cooldown completes → budget reset → restart attempted."""
    dummy = register_dummy_service(
        watcher,
        restart_type=RestartType.TRANSIENT,
        budget_intensity=1,
        cooldown_seconds=0.05,  # very short cooldown for test speed
    )

    # Use up the budget (1 restart)
    await restart_and_await(watcher, dummy.failed_event)

    # Exhaust budget — should schedule cooldown task (budget check is synchronous)
    await watcher.restart_service(dummy.failed_event)

    assert dummy.key in watcher._cooldown_tasks
    cooldown_task = watcher._cooldown_tasks[dummy.key]

    # Wait for the cooldown task to complete
    await asyncio.wait_for(asyncio.shield(cooldown_task), timeout=2.0)

    # After cooldown, budget should have been reset and restart attempted
    if watcher._budgets.get(dummy.key):
        assert budget_entries(watcher, dummy.key) == 0 or dummy.calls["start"] >= 2


async def test_max_cooldown_cycles_exceeded(watcher: ServiceWatcher):
    """TRANSIENT with max_cooldown_cycles=1: second exhaustion → EXHAUSTED_DEAD."""
    hassette = watcher.hassette
    dummy = register_dummy_service(
        watcher,
        restart_type=RestartType.TRANSIENT,
        budget_intensity=1,
        cooldown_seconds=0.01,
        max_cooldown_cycles=1,
    )

    # Set cycle count to max+1 to simulate exceeding max.
    # Also put the service in EXHAUSTED_COOLING — the valid pre-condition for cooldown_and_retry
    # (in production, handle_exhaustion sets this before spawning the cooldown task).
    watcher._cooldown_cycles[dummy.key] = 2  # already exceeded max_cooldown_cycles=1
    dummy.service._status = ResourceStatus.EXHAUSTED_COOLING

    # Run cooldown_and_retry directly — should detect exceeded cycles and emit EXHAUSTED_DEAD
    with EventCapture.capturing(hassette) as capture:
        await watcher.cooldown_and_retry(dummy.service.class_name, dummy.service.role, dummy.key, dummy.spec)

    assert len(capture.events) == 1
    assert capture.events[0].payload.data.status == ResourceStatus.EXHAUSTED_DEAD


async def test_concurrent_failures_independent_budgets(watcher: ServiceWatcher):
    """Two services fail simultaneously — each tracked by its own budget."""
    hassette = watcher.hassette

    counts_a = make_call_counts()
    counts_b = make_call_counts()

    spec = make_fast_spec(restart_type=RestartType.TRANSIENT, budget_intensity=5)

    class _DummyA(Service):
        restart_spec: ClassVar[RestartSpec] = spec

        async def serve(self):
            pass

        async def on_shutdown(self):
            counts_a["cancel"] += 1

        async def on_initialize(self):
            counts_a["start"] += 1

    class _DummyB(Service):
        restart_spec: ClassVar[RestartSpec] = spec

        async def serve(self):
            pass

        async def on_shutdown(self):
            counts_b["cancel"] += 1

        async def on_initialize(self):
            counts_b["start"] += 1

    service_a = _DummyA(hassette)
    service_b = _DummyB(hassette)
    hassette.children.extend([service_a, service_b])

    event_a = make_service_failed_event(service_a)
    event_b = make_service_failed_event(service_b)

    key_a = watcher.service_key(service_a.class_name, service_a.role)
    key_b = watcher.service_key(service_b.class_name, service_b.role)

    # Fail both services
    await asyncio.gather(
        watcher.restart_service(event_a),
        watcher.restart_service(event_b),
    )

    assert key_a in watcher._budgets
    assert key_b in watcher._budgets

    # Each should have independent budget with 1 restart recorded
    assert budget_entries(watcher, key_a) == 1
    assert budget_entries(watcher, key_b) == 1


async def test_restart_exception_caught_no_double_count(watcher: ServiceWatcher):
    """on_initialize raises → exception caught and logged, budget not double-counted."""
    dummy = register_dummy_service(watcher, fail=True, restart_type=RestartType.TRANSIENT, budget_intensity=10)

    await restart_and_await(watcher, dummy.failed_event)

    # Only 1 budget entry recorded (before restart), not 2
    assert budget_entries(watcher, dummy.key) == 1

    # In-restart flag should be cleared after exception
    assert dummy.key not in watcher._restarting


async def test_bus_recovery_reconciliation(watcher: ServiceWatcher):
    """BusService restarts, another service is in FAILED state during blind window → reconciliation picks it up."""
    dummy = register_dummy_service(watcher, restart_type=RestartType.TRANSIENT, budget_intensity=5)

    # Simulate the service being in FAILED state with no budget entry
    # (as if FAILED event was dropped during BusService restart).
    # Use ._status bypass — this is deliberate test fixture setup, not a lifecycle operation.
    dummy.service._status = ResourceStatus.FAILED
    assert dummy.key not in watcher._budgets  # no budget entry — dropped during blind window

    # Run reconciliation
    await watcher.reconcile_after_bus_recovery()

    # Reconciliation should have picked up the FAILED service and entered restart flow
    assert budget_entries(watcher, dummy.key) == 1, "Reconciliation should have recorded one restart"
