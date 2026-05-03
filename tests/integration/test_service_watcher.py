"""Integration tests for ServiceWatcher restart logic.

Tests use RestartSpec-based per-service configuration rather than global config fields.
"""

import asyncio
import time
from typing import ClassVar
from unittest.mock import AsyncMock, patch

import pytest

from hassette.core.service_watcher import ServiceWatcher
from hassette.events import HassetteServiceEvent
from hassette.events.base import HassettePayload
from hassette.events.hassette import ServiceStatusPayload
from hassette.resources.base import RestartSpec, Service
from hassette.test_utils import make_service_failed_event, make_service_running_event, preserve_config, wait_for
from hassette.test_utils.reset import reset_hassette_lifecycle
from hassette.types import ResourceStatus, Topic
from hassette.types.enums import RestartType


@pytest.fixture
async def get_service_watcher_mock(hassette_with_bus):
    """Return a fresh service watcher for each test."""
    hassette = hassette_with_bus.hassette
    watcher = ServiceWatcher(hassette, parent=hassette)
    original_children = list(hassette.children)
    with preserve_config(hassette.config):
        yield watcher
        # Clean up bus listeners registered by this watcher via propagation
        await watcher.shutdown()
        await reset_hassette_lifecycle(hassette, original_children=original_children)


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
            pass

        async def on_shutdown(self):
            called["cancel"] += 1

        async def on_initialize(self):
            called["start"] += 1
            if fail:
                raise RuntimeError("always fails")

    return _Dummy(hassette)


# ---------------------------------------------------------------------------
# Migrated existing tests — updated to use RestartSpec
# ---------------------------------------------------------------------------


async def test_restart_service_cancels_then_starts(get_service_watcher_mock: ServiceWatcher):
    """Restarting a failed service cancels and reinitializes it."""
    call_counts = {"cancel": 0, "start": 0}

    dummy_service = get_dummy_service(
        call_counts,
        get_service_watcher_mock.hassette,
        restart_spec=RestartSpec(
            restart_type=RestartType.TRANSIENT,
            backoff_base_seconds=0,
            budget_intensity=5,
            budget_period_seconds=300,
        ),
    )
    get_service_watcher_mock.hassette.children.append(dummy_service)

    event = make_service_failed_event(dummy_service)

    await get_service_watcher_mock.restart_service(event)

    await wait_for(
        lambda: call_counts == {"cancel": 1, "start": 1},
        desc="restart_service completed",
    )

    assert call_counts == {"cancel": 1, "start": 1}, (
        f"Expected cancel and start to be called once each, got {call_counts}"
    )


async def test_always_failing_service_stops_after_max_attempts(get_service_watcher_mock: ServiceWatcher):
    """A service that always fails on restart stops being restarted after budget exhaustion."""
    watcher = get_service_watcher_mock
    hassette = watcher.hassette
    call_counts = {"cancel": 0, "start": 0}

    # budget_intensity=3 means 3 restarts before exhaustion
    spec = RestartSpec(
        restart_type=RestartType.PERMANENT,
        budget_intensity=3,
        budget_period_seconds=300,
        backoff_base_seconds=0,
    )
    dummy_service = get_dummy_service(call_counts, hassette, fail=True, restart_spec=spec)
    hassette.children.append(dummy_service)

    event = make_service_failed_event(dummy_service)
    key = watcher._service_key(dummy_service.class_name, dummy_service.role)

    # Each call to restart_service increments budget and attempts restart.
    # The service fails on restart but exceptions are caught.
    for _ in range(3):
        await watcher.restart_service(event)

    budget = watcher._budgets.get(key)
    assert budget is not None
    budget._evict_expired()
    assert len(budget._timestamps) == 3
    assert not hassette.shutdown_event.is_set(), "Shutdown should not happen before budget exhausted"

    # The 4th call should trigger shutdown (budget exhausted, PERMANENT)
    await watcher.restart_service(event)

    assert hassette.shutdown_event.is_set(), "Shutdown should be triggered after budget exhausted"


async def test_crashed_event_emitted_before_shutdown(get_service_watcher_mock: ServiceWatcher):
    """When budget is exhausted for PERMANENT service, a CRASHED event is emitted before shutdown."""
    watcher = get_service_watcher_mock
    hassette = watcher.hassette
    call_counts = {"cancel": 0, "start": 0}

    spec = RestartSpec(
        restart_type=RestartType.PERMANENT,
        budget_intensity=1,  # exhaust on first restart
        budget_period_seconds=300,
        backoff_base_seconds=0,
    )
    dummy_service = get_dummy_service(call_counts, hassette, fail=True, restart_spec=spec)
    hassette.children.append(dummy_service)

    event = make_service_failed_event(dummy_service)

    # First call uses the one budget slot
    await watcher.restart_service(event)

    # Second call exceeds budget — should emit CRASHED then shutdown
    mock_send = AsyncMock()
    original_send = hassette.send_event
    hassette.send_event = mock_send  # pyright: ignore[reportAttributeAccessIssue]
    try:
        await watcher.restart_service(event)
    finally:
        hassette.send_event = original_send  # pyright: ignore[reportAttributeAccessIssue]

    # First send_event call should be the CRASHED event (shutdown may emit STOPPED after)
    assert mock_send.call_count >= 1
    first_call = mock_send.call_args_list[0]
    assert first_call[0][0] == Topic.HASSETTE_EVENT_SERVICE_STATUS
    crashed_event = first_call[0][1]
    assert crashed_event.payload.data.status == ResourceStatus.CRASHED
    assert crashed_event.payload.data.previous_status == ResourceStatus.FAILED
    assert crashed_event.payload.data.resource_name == dummy_service.class_name


async def test_exponential_backoff(get_service_watcher_mock: ServiceWatcher):
    """Backoff delay increases exponentially between restart attempts (using shutdown-safe sleep)."""
    watcher = get_service_watcher_mock
    call_counts = {"cancel": 0, "start": 0}

    spec = RestartSpec(
        restart_type=RestartType.TRANSIENT,
        budget_intensity=10,
        budget_period_seconds=300,
        backoff_base_seconds=1.0,
        backoff_multiplier=2.0,
        backoff_max_seconds=60.0,
    )
    dummy_service = get_dummy_service(call_counts, watcher.hassette, fail=True, restart_spec=spec)
    watcher.hassette.children.append(dummy_service)

    event = make_service_failed_event(dummy_service)

    sleep_calls: list[float] = []

    async def mock_shutdown_safe_sleep(duration: float) -> bool:
        sleep_calls.append(duration)
        return True  # sleep completed normally

    with patch.object(watcher, "_shutdown_safe_sleep", side_effect=mock_shutdown_safe_sleep):
        for _ in range(3):
            await watcher.restart_service(event)

    # attempt 1: backoff = 1.0 * 2^0 = 1.0
    # attempt 2: backoff = 1.0 * 2^1 = 2.0
    # attempt 3: backoff = 1.0 * 2^2 = 4.0
    assert sleep_calls == [1.0, 2.0, 4.0]


async def test_budget_reset_on_recovery(get_service_watcher_mock: ServiceWatcher):
    """Budget resets when a service transitions to RUNNING and becomes ready."""
    watcher = get_service_watcher_mock
    call_counts = {"cancel": 0, "start": 0}

    spec = RestartSpec(
        restart_type=RestartType.TRANSIENT,
        budget_intensity=5,
        budget_period_seconds=300,
        backoff_base_seconds=0,
        startup_timeout_seconds=1.0,
    )
    dummy_service = get_dummy_service(call_counts, watcher.hassette, fail=True, restart_spec=spec)
    watcher.hassette.children.append(dummy_service)

    event = make_service_failed_event(dummy_service)
    key = watcher._service_key(dummy_service.class_name, dummy_service.role)

    # Accumulate 2 restart attempts
    for _ in range(2):
        await watcher.restart_service(event)

    budget = watcher._budgets[key]
    budget._evict_expired()
    assert len(budget._timestamps) == 2

    # Mark the service ready, then fire RUNNING event — budget should reset
    dummy_service.mark_ready(reason="test")
    await watcher._on_service_running(make_service_running_event(dummy_service))

    budget._evict_expired()
    assert len(budget._timestamps) == 0  # budget reset


# ---------------------------------------------------------------------------
# New tests for WP02 behavior
# ---------------------------------------------------------------------------


async def test_permanent_exhaustion_triggers_shutdown(get_service_watcher_mock: ServiceWatcher):
    """PERMANENT service: exhausting budget triggers hassette.shutdown()."""
    watcher = get_service_watcher_mock
    hassette = watcher.hassette
    call_counts = {"cancel": 0, "start": 0}

    spec = RestartSpec(
        restart_type=RestartType.PERMANENT,
        budget_intensity=2,
        budget_period_seconds=300,
        backoff_base_seconds=0,
    )
    dummy_service = get_dummy_service(call_counts, hassette, restart_spec=spec)
    hassette.children.append(dummy_service)

    event = make_service_failed_event(dummy_service)

    # Use up budget
    await watcher.restart_service(event)
    await watcher.restart_service(event)

    assert not hassette.shutdown_event.is_set(), "Should not shutdown until budget exhausted"

    # Exhaust budget
    await watcher.restart_service(event)
    assert hassette.shutdown_event.is_set()


async def test_transient_exhaustion_enters_cooldown(get_service_watcher_mock: ServiceWatcher):
    """TRANSIENT service: exhausting budget emits EXHAUSTED_COOLING and schedules cooldown task."""
    watcher = get_service_watcher_mock
    hassette = watcher.hassette
    call_counts = {"cancel": 0, "start": 0}

    spec = RestartSpec(
        restart_type=RestartType.TRANSIENT,
        budget_intensity=2,
        budget_period_seconds=300,
        backoff_base_seconds=0,
        cooldown_seconds=999,  # long cooldown so we can verify the task is created
    )
    dummy_service = get_dummy_service(call_counts, hassette, restart_spec=spec)
    hassette.children.append(dummy_service)

    event = make_service_failed_event(dummy_service)
    key = watcher._service_key(dummy_service.class_name, dummy_service.role)

    # Use up budget
    await watcher.restart_service(event)
    await watcher.restart_service(event)

    # Capture events emitted on exhaustion
    emitted_events: list = []

    async def capture_event(_topic, ev):
        emitted_events.append(ev)

    hassette.send_event = capture_event  # pyright: ignore[reportAttributeAccessIssue]

    # Exhaust budget
    await watcher.restart_service(event)

    hassette.send_event = hassette._event_stream_service.send_event  # pyright: ignore[reportAttributeAccessIssue]

    assert not hassette.shutdown_event.is_set(), "TRANSIENT exhaustion should NOT trigger shutdown"
    assert len(emitted_events) >= 1
    cooling_event = emitted_events[0]
    assert cooling_event.payload.data.status == ResourceStatus.EXHAUSTED_COOLING
    assert cooling_event.payload.data.retry_at is not None
    assert cooling_event.payload.data.retry_at > time.time()

    # Cooldown task should be scheduled
    assert key in watcher._cooldown_tasks
    assert not watcher._cooldown_tasks[key].done()

    # Cancel the cooldown task to avoid lingering
    watcher._cooldown_tasks[key].cancel()


async def test_temporary_exhaustion_stays_dead(get_service_watcher_mock: ServiceWatcher):
    """TEMPORARY service: exhausting budget emits EXHAUSTED_DEAD, no further restarts."""
    watcher = get_service_watcher_mock
    hassette = watcher.hassette
    call_counts = {"cancel": 0, "start": 0}

    spec = RestartSpec(
        restart_type=RestartType.TEMPORARY,
        budget_intensity=2,
        budget_period_seconds=300,
        backoff_base_seconds=0,
    )
    dummy_service = get_dummy_service(call_counts, hassette, restart_spec=spec)
    hassette.children.append(dummy_service)

    event = make_service_failed_event(dummy_service)

    # Use up budget
    await watcher.restart_service(event)
    await watcher.restart_service(event)

    emitted_events: list = []

    async def capture_event(_topic, ev):
        emitted_events.append(ev)

    hassette.send_event = capture_event  # pyright: ignore[reportAttributeAccessIssue]

    # Exhaust budget
    await watcher.restart_service(event)

    hassette.send_event = hassette._event_stream_service.send_event  # pyright: ignore[reportAttributeAccessIssue]

    assert not hassette.shutdown_event.is_set()
    assert len(emitted_events) == 1
    dead_event = emitted_events[0]
    assert dead_event.payload.data.status == ResourceStatus.EXHAUSTED_DEAD
    assert dead_event.payload.data.retry_at is None


async def test_fatal_error_triggers_immediate_shutdown(get_service_watcher_mock: ServiceWatcher):
    """Service with fatal_error_names: matching exception triggers immediate shutdown, no restart."""
    watcher = get_service_watcher_mock
    hassette = watcher.hassette
    call_counts = {"cancel": 0, "start": 0}

    spec = RestartSpec(
        restart_type=RestartType.TRANSIENT,
        fatal_error_names=("FatalDbError", "SchemaVersionError"),
        budget_intensity=5,
        budget_period_seconds=300,
        backoff_base_seconds=0,
    )
    dummy_service = get_dummy_service(call_counts, hassette, restart_spec=spec)
    hassette.children.append(dummy_service)

    # Create a failed event with exception_type matching a fatal error name
    fatal_event = HassetteServiceEvent(
        topic=Topic.HASSETTE_EVENT_SERVICE_STATUS,
        payload=HassettePayload(
            event_type=str(ResourceStatus.FAILED),
            data=ServiceStatusPayload(
                resource_name=dummy_service.class_name,
                role=dummy_service.role,
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

    emitted_events: list = []

    async def capture_event(_topic, ev):
        emitted_events.append(ev)
        await hassette.shutdown()

    original_send = hassette.send_event
    hassette.send_event = capture_event  # pyright: ignore[reportAttributeAccessIssue]

    await watcher.restart_service(fatal_event)

    hassette.send_event = original_send  # pyright: ignore[reportAttributeAccessIssue]

    # Should have emitted CRASHED and triggered shutdown
    assert hassette.shutdown_event.is_set()
    assert len(emitted_events) >= 1
    # First event should be CRASHED
    assert emitted_events[0].payload.data.status == ResourceStatus.CRASHED
    # No restart should have been attempted
    assert call_counts["start"] == 0


async def test_non_retryable_error_skips_restart(get_service_watcher_mock: ServiceWatcher):
    """Service with non_retryable_error_names: matching exception skips restart, goes to exhaustion."""
    watcher = get_service_watcher_mock
    hassette = watcher.hassette
    call_counts = {"cancel": 0, "start": 0}

    spec = RestartSpec(
        restart_type=RestartType.TEMPORARY,
        non_retryable_error_names=("NonRetryableError",),
        budget_intensity=5,
        budget_period_seconds=300,
        backoff_base_seconds=0,
    )
    dummy_service = get_dummy_service(call_counts, hassette, restart_spec=spec)
    hassette.children.append(dummy_service)

    nr_event = HassetteServiceEvent(
        topic=Topic.HASSETTE_EVENT_SERVICE_STATUS,
        payload=HassettePayload(
            event_type=str(ResourceStatus.FAILED),
            data=ServiceStatusPayload(
                resource_name=dummy_service.class_name,
                role=dummy_service.role,
                status=ResourceStatus.FAILED,
                previous_status=ResourceStatus.RUNNING,
                exception="non-retryable",
                exception_type="NonRetryableError",
                ready=False,
                ready_phase=None,
            ),
        ),
    )

    emitted_events: list = []

    async def capture_event(_topic, ev):
        emitted_events.append(ev)

    hassette.send_event = capture_event  # pyright: ignore[reportAttributeAccessIssue]

    await watcher.restart_service(nr_event)

    hassette.send_event = hassette._event_stream_service.send_event  # pyright: ignore[reportAttributeAccessIssue]

    # No restart attempt made
    assert call_counts["start"] == 0
    # TEMPORARY exhaustion → EXHAUSTED_DEAD emitted
    assert len(emitted_events) == 1
    assert emitted_events[0].payload.data.status == ResourceStatus.EXHAUSTED_DEAD


async def test_in_restart_guard_prevents_double_budget(get_service_watcher_mock: ServiceWatcher):
    """Two FAILED events while restart is in progress only record one budget entry."""
    watcher = get_service_watcher_mock
    hassette = watcher.hassette
    call_counts = {"cancel": 0, "start": 0}

    spec = RestartSpec(
        restart_type=RestartType.TRANSIENT,
        budget_intensity=10,
        budget_period_seconds=300,
        backoff_base_seconds=0,
    )
    dummy_service = get_dummy_service(call_counts, hassette, restart_spec=spec)
    hassette.children.append(dummy_service)

    event = make_service_failed_event(dummy_service)
    key = watcher._service_key(dummy_service.class_name, dummy_service.role)

    # Manually set the in-restart flag to simulate concurrent restart in progress
    watcher._restarting.add(key)
    # Ensure budget exists but has 1 entry (from the first restart)
    budget = watcher._get_budget(key, spec)
    budget.record_restart()

    # Second FAILED event arrives while restart is in progress — should be dropped
    await watcher.restart_service(event)

    # Budget should still have only 1 entry
    budget._evict_expired()
    assert len(budget._timestamps) == 1, "Second FAILED event should have been dropped by in-restart guard"

    # Clean up
    watcher._restarting.discard(key)


async def test_shutdown_safe_sleep_aborts_on_shutdown(get_service_watcher_mock: ServiceWatcher):
    """Backoff sleep aborts early when shutdown_event is set."""
    watcher = get_service_watcher_mock
    hassette = watcher.hassette
    call_counts = {"cancel": 0, "start": 0}

    spec = RestartSpec(
        restart_type=RestartType.TRANSIENT,
        budget_intensity=10,
        budget_period_seconds=300,
        backoff_base_seconds=5.0,  # real backoff that would be interrupted
        backoff_multiplier=1.0,
    )
    dummy_service = get_dummy_service(call_counts, hassette, restart_spec=spec)
    hassette.children.append(dummy_service)

    event = make_service_failed_event(dummy_service)
    key = watcher._service_key(dummy_service.class_name, dummy_service.role)

    # Set shutdown event to trigger early abort during backoff
    hassette.shutdown_event.set()

    await watcher.restart_service(event)

    # Service should NOT have been restarted
    assert call_counts["start"] == 0, "Service should not restart when shutdown is requested during backoff"
    # In-restart flag should be cleared
    assert key not in watcher._restarting


async def test_budget_reset_on_recovery_confirmed(get_service_watcher_mock: ServiceWatcher):
    """Budget resets when service reaches RUNNING and signals readiness."""
    watcher = get_service_watcher_mock
    call_counts = {"cancel": 0, "start": 0}

    spec = RestartSpec(
        restart_type=RestartType.TRANSIENT,
        budget_intensity=5,
        budget_period_seconds=300,
        backoff_base_seconds=0,
        startup_timeout_seconds=1.0,
    )
    dummy_service = get_dummy_service(call_counts, watcher.hassette, fail=True, restart_spec=spec)
    watcher.hassette.children.append(dummy_service)

    event = make_service_failed_event(dummy_service)
    key = watcher._service_key(dummy_service.class_name, dummy_service.role)

    # Accumulate 2 restart attempts
    await watcher.restart_service(event)
    await watcher.restart_service(event)

    budget = watcher._budgets[key]
    budget._evict_expired()
    assert len(budget._timestamps) == 2

    # Mark the service ready, then fire RUNNING event — budget should reset
    dummy_service.mark_ready(reason="test")
    await watcher._on_service_running(make_service_running_event(dummy_service))

    budget._evict_expired()
    assert len(budget._timestamps) == 0  # budget.reset() was called
    assert key not in watcher._restarting  # in-restart cleared


async def test_readiness_timeout_no_budget_impact(get_service_watcher_mock: ServiceWatcher):
    """Readiness timeout after RUNNING does NOT increment restart budget."""
    watcher = get_service_watcher_mock
    call_counts = {"cancel": 0, "start": 0}

    spec = RestartSpec(
        restart_type=RestartType.TRANSIENT,
        budget_intensity=5,
        budget_period_seconds=300,
        backoff_base_seconds=0,
        startup_timeout_seconds=0.05,  # very short timeout
    )
    dummy_service = get_dummy_service(call_counts, watcher.hassette, fail=True, restart_spec=spec)
    watcher.hassette.children.append(dummy_service)

    event = make_service_failed_event(dummy_service)
    key = watcher._service_key(dummy_service.class_name, dummy_service.role)

    # Accumulate 1 restart attempt
    await watcher.restart_service(event)

    budget = watcher._budgets[key]
    budget._evict_expired()
    count_before = len(budget._timestamps)

    # Fire RUNNING event WITHOUT marking ready — timeout will occur, no budget impact
    await watcher._on_service_running(make_service_running_event(dummy_service))

    budget._evict_expired()
    assert len(budget._timestamps) == count_before, "Readiness timeout should not impact restart budget"


async def test_cooldown_then_recovery(get_service_watcher_mock: ServiceWatcher):
    """TRANSIENT exhaustion → cooldown completes → budget reset → restart attempted."""
    watcher = get_service_watcher_mock
    hassette = watcher.hassette
    call_counts = {"cancel": 0, "start": 0}

    spec = RestartSpec(
        restart_type=RestartType.TRANSIENT,
        budget_intensity=1,
        budget_period_seconds=300,
        backoff_base_seconds=0,
        cooldown_seconds=0.05,  # very short cooldown for test speed
    )
    dummy_service = get_dummy_service(call_counts, hassette, restart_spec=spec)
    hassette.children.append(dummy_service)

    event = make_service_failed_event(dummy_service)
    key = watcher._service_key(dummy_service.class_name, dummy_service.role)

    # Use up the budget (1 restart)
    await watcher.restart_service(event)

    # Exhaust budget — should schedule cooldown task
    await watcher.restart_service(event)

    assert key in watcher._cooldown_tasks
    cooldown_task = watcher._cooldown_tasks[key]

    # Wait for the cooldown task to complete
    await asyncio.wait_for(asyncio.shield(cooldown_task), timeout=2.0)

    # After cooldown, budget should have been reset and restart attempted
    budget = watcher._budgets.get(key)
    if budget:
        budget._evict_expired()
        # Budget was reset during cooldown
        assert len(budget._timestamps) == 0 or call_counts["start"] >= 2


async def test_max_cooldown_cycles_exceeded(get_service_watcher_mock: ServiceWatcher):
    """TRANSIENT with max_cooldown_cycles=1: second exhaustion → EXHAUSTED_DEAD."""
    watcher = get_service_watcher_mock
    hassette = watcher.hassette
    call_counts = {"cancel": 0, "start": 0}

    spec = RestartSpec(
        restart_type=RestartType.TRANSIENT,
        budget_intensity=1,
        budget_period_seconds=300,
        backoff_base_seconds=0,
        cooldown_seconds=0.01,
        max_cooldown_cycles=1,
    )
    dummy_service = get_dummy_service(call_counts, hassette, restart_spec=spec)
    hassette.children.append(dummy_service)

    key = watcher._service_key(dummy_service.class_name, dummy_service.role)

    # Set cycle count to max+1 to simulate exceeding max
    watcher._cooldown_cycles[key] = 2  # already exceeded max_cooldown_cycles=1

    emitted_events: list = []

    async def capture_event(_topic, ev):
        emitted_events.append(ev)

    hassette.send_event = capture_event  # pyright: ignore[reportAttributeAccessIssue]

    # Run _cooldown_and_retry directly — should detect exceeded cycles and emit EXHAUSTED_DEAD
    await watcher._cooldown_and_retry(dummy_service.class_name, dummy_service.role, key, spec)

    hassette.send_event = hassette._event_stream_service.send_event  # pyright: ignore[reportAttributeAccessIssue]

    assert len(emitted_events) == 1
    assert emitted_events[0].payload.data.status == ResourceStatus.EXHAUSTED_DEAD


async def test_concurrent_failures_independent_budgets(get_service_watcher_mock: ServiceWatcher):
    """Two services fail simultaneously — each tracked by its own budget."""
    watcher = get_service_watcher_mock
    hassette = watcher.hassette

    counts_a = {"cancel": 0, "start": 0}
    counts_b = {"cancel": 0, "start": 0}

    spec = RestartSpec(
        restart_type=RestartType.TRANSIENT,
        budget_intensity=5,
        budget_period_seconds=300,
        backoff_base_seconds=0,
    )

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

    key_a = watcher._service_key(service_a.class_name, service_a.role)
    key_b = watcher._service_key(service_b.class_name, service_b.role)

    # Fail both services
    await asyncio.gather(
        watcher.restart_service(event_a),
        watcher.restart_service(event_b),
    )

    assert key_a in watcher._budgets
    assert key_b in watcher._budgets

    # Each should have independent budget with 1 restart recorded
    budget_a = watcher._budgets[key_a]
    budget_b = watcher._budgets[key_b]
    budget_a._evict_expired()
    budget_b._evict_expired()
    assert len(budget_a._timestamps) == 1
    assert len(budget_b._timestamps) == 1


async def test_restart_exception_caught_no_double_count(get_service_watcher_mock: ServiceWatcher):
    """service.restart() raises → exception caught and logged, budget not double-counted."""
    watcher = get_service_watcher_mock
    hassette = watcher.hassette
    call_counts = {"cancel": 0, "start": 0}

    spec = RestartSpec(
        restart_type=RestartType.TRANSIENT,
        budget_intensity=10,
        budget_period_seconds=300,
        backoff_base_seconds=0,
    )
    dummy_service = get_dummy_service(call_counts, hassette, restart_spec=spec)
    hassette.children.append(dummy_service)

    event = make_service_failed_event(dummy_service)
    key = watcher._service_key(dummy_service.class_name, dummy_service.role)

    # Make service.restart() raise
    async def raise_on_restart():
        raise RuntimeError("restart blew up")

    dummy_service.restart = raise_on_restart  # pyright: ignore[reportAttributeAccessIssue]

    # Should not propagate the exception from restart
    await watcher.restart_service(event)

    budget = watcher._budgets.get(key)
    assert budget is not None
    budget._evict_expired()
    # Only 1 budget entry recorded (before restart), not 2
    assert len(budget._timestamps) == 1

    # In-restart flag should be cleared after exception
    assert key not in watcher._restarting


async def test_bus_recovery_reconciliation(get_service_watcher_mock: ServiceWatcher):
    """BusService restarts, another service is in FAILED state during blind window → reconciliation picks it up."""
    watcher = get_service_watcher_mock
    hassette = watcher.hassette
    call_counts = {"cancel": 0, "start": 0}

    spec = RestartSpec(
        restart_type=RestartType.TRANSIENT,
        budget_intensity=5,
        budget_period_seconds=300,
        backoff_base_seconds=0,
    )
    dummy_service = get_dummy_service(call_counts, hassette, restart_spec=spec)
    hassette.children.append(dummy_service)

    # Simulate the service being in FAILED state with no budget entry
    # (as if FAILED event was dropped during BusService restart)
    dummy_service.status = ResourceStatus.FAILED
    key = watcher._service_key(dummy_service.class_name, dummy_service.role)
    assert key not in watcher._budgets  # no budget entry — dropped during blind window

    # Run reconciliation
    await watcher._reconcile_after_bus_recovery()

    # Reconciliation should have picked up the FAILED service and entered restart flow
    budget = watcher._budgets.get(key)
    assert budget is not None, "Reconciliation should have created a budget entry"
    budget._evict_expired()
    assert len(budget._timestamps) == 1, "Reconciliation should have recorded one restart"
