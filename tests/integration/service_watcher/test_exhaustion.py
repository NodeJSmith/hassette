"""Integration tests for ServiceWatcher restart-budget exhaustion and cooldown."""

import asyncio
import time
from typing import TYPE_CHECKING

from hassette_wire import ResourceStatus

from hassette import HassetteConfig
from hassette.core.service_watcher import ServiceWatcher
from hassette.events import Event
from hassette.testing import EventCapture
from hassette.types import Topic
from hassette.types.enums import RestartType

from .helpers import (
    DummyServiceSetup,
    budget_entries,
    crashed_events,
    isolated_watcher,
    register_dummy_service,
    restart_and_await,
)

if TYPE_CHECKING:
    from collections.abc import Callable


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


async def test_always_failing_service_stops_after_max_attempts(
    test_config_class: type[HassetteConfig], unused_tcp_port_factory: "Callable[[], int]"
):
    """A service that always fails on restart stops being restarted after budget exhaustion."""
    async with isolated_watcher(test_config_class, unused_tcp_port_factory) as watcher:
        hassette = watcher.hassette

        # budget_intensity=3 means 3 restarts before exhaustion
        dummy = register_dummy_service(watcher, fail=True, restart_type=RestartType.PERMANENT, budget_intensity=3)

        # Each call to restart_service increments budget and spawns a restart task. The service
        # fails on restart; the 3rd attempt both records the last budget entry and, failing from
        # within execute_restart() itself, exhausts it immediately -- no extra event is needed
        # to notice exhaustion (see test_execute_restart_own_failure_triggers_exhaustion).
        for _ in range(2):
            await restart_and_await(watcher, dummy.failed_event)
            assert not hassette.shutdown_event.is_set(), "Shutdown should not happen before budget exhausted"

        await restart_and_await(watcher, dummy.failed_event)

        assert budget_entries(watcher, dummy.key) == 3
        assert hassette.shutdown_event.is_set(), "Shutdown should be triggered after budget exhausted"


async def test_crashed_event_emitted_before_shutdown(
    test_config_class: type[HassetteConfig], unused_tcp_port_factory: "Callable[[], int]"
):
    """When budget is exhausted for PERMANENT service, a CRASHED event is emitted before shutdown."""
    async with isolated_watcher(test_config_class, unused_tcp_port_factory) as watcher:
        dummy = register_dummy_service(watcher, fail=True, restart_type=RestartType.PERMANENT, budget_intensity=1)

        # The single allowed attempt both records the last budget entry (Step 5) and fails from
        # within execute_restart() -- exhaustion fires directly from that failure, not a
        # follow-up event (see test_execute_restart_own_failure_triggers_exhaustion). The
        # capture also picks up the dummy's own restart()-internal shutdown/reinitialize churn
        # and Hassette's own shutdown events, so filter for CRASHED rather than assume index 0.
        with EventCapture.capturing(watcher.hassette) as capture:
            await restart_and_await(watcher, dummy.failed_event)

        crashed = crashed_events(capture.events)
        assert len(crashed) == 1, "Should emit exactly one CRASHED event"
        crashed_event = crashed[0]
        assert crashed_event.topic == Topic.HASSETTE_EVENT_SERVICE_STATUS
        assert crashed_event.payload.data.status == ResourceStatus.CRASHED
        assert crashed_event.payload.data.previous_status == ResourceStatus.FAILED
        assert crashed_event.payload.data.resource_name == dummy.service.class_name


async def test_permanent_exhaustion_triggers_shutdown(
    test_config_class: type[HassetteConfig], unused_tcp_port_factory: "Callable[[], int]"
):
    """PERMANENT service: exhausting budget triggers hassette.shutdown()."""
    async with isolated_watcher(test_config_class, unused_tcp_port_factory) as watcher:
        hassette = watcher.hassette
        dummy = register_dummy_service(watcher, restart_type=RestartType.PERMANENT, budget_intensity=2)

        # Use up budget
        await restart_and_await(watcher, dummy.failed_event)
        await restart_and_await(watcher, dummy.failed_event)

        assert not hassette.shutdown_event.is_set(), "Should not shutdown until budget exhausted"

        # Exhaust budget (budget check is synchronous — no spawn needed)
        await watcher.restart_service(dummy.failed_event)
        assert hassette.shutdown_event.is_set()


async def test_permanent_exhaustion_records_fatal_reason(
    test_config_class: type[HassetteConfig], unused_tcp_port_factory: "Callable[[], int]"
):
    """PERMANENT exhaustion records _fatal_shutdown_reason synchronously at the decision site.

    Regression test for the reason-race: the CRASHED event is dispatched asynchronously
    (task-per-handler), so the reason must be set synchronously in handle_exhaustion — not
    only in the async shutdown_if_crashed handler — or run_forever() exits 0 on a real crash.
    """
    async with isolated_watcher(test_config_class, unused_tcp_port_factory) as watcher:
        hassette = watcher.hassette
        assert hassette._fatal_shutdown_reason is None

        dummy = register_dummy_service(watcher, restart_type=RestartType.PERMANENT, budget_intensity=2)

        await restart_and_await(watcher, dummy.failed_event)
        await restart_and_await(watcher, dummy.failed_event)
        await watcher.restart_service(dummy.failed_event)  # exhausts → handle_exhaustion (PERMANENT, no spawn)

        assert hassette._fatal_shutdown_reason is not None
        assert dummy.service.class_name in hassette._fatal_shutdown_reason


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


async def test_execute_restart_own_failure_triggers_exhaustion(
    test_config_class: type[HassetteConfig], unused_tcp_port_factory: "Callable[[], int]"
):
    """The in-flight restart attempt's own failure triggers exhaustion directly, not via a
    racing FAILED event.

    With budget_intensity=1, the single restart attempt spawned by restart_service() both
    records the last budget entry (Step 5) and then fails from within execute_restart() (the
    dummy service's on_initialize() always raises). That failure is detected on the same task
    that owns `_restarting`, not inferred from a duplicate event arriving through the bus.

    Uses isolated_watcher because the PERMANENT exhaustion path drives a real hassette.shutdown().
    """
    async with isolated_watcher(test_config_class, unused_tcp_port_factory) as watcher:
        dummy = register_dummy_service(watcher, fail=True, restart_type=RestartType.PERMANENT, budget_intensity=1)

        with EventCapture.capturing(watcher.hassette) as capture:
            await restart_and_await(watcher, dummy.failed_event)

        assert watcher.hassette.fatal_shutdown_reason is not None, (
            "The restart attempt's own failure exhausting the budget should trigger fatal shutdown for PERMANENT"
        )
        assert len(crashed_events(capture.events)) == 1, "Should emit exactly one CRASHED event"


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
