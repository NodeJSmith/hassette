"""Integration tests for ServiceWatcher restart logic.

Tests use RestartSpec-based per-service configuration rather than global config fields.
"""

import asyncio
from typing import ClassVar
from unittest.mock import patch

from hassette_wire import ResourceStatus

from hassette import context
from hassette.core.service_watcher import ServiceWatcher
from hassette.events import HassetteServiceEvent
from hassette.resources.lifecycle import mark_ready
from hassette.resources.restart import RestartSpec
from hassette.resources.service import Service
from hassette.testing import EventCapture, wait_for
from hassette.types.enums import ResourceRole, RestartType
from tests.support.helpers import (
    make_service_failed_event,
    make_service_running_event,
)

from .helpers import (
    ALWAYS_FAIL,
    AWAIT_TIMEOUT,
    budget_entries,
    make_call_counts,
    make_fast_spec,
    mark_failed,
    register_dummy_service,
    restart_and_await,
)


async def on_running_and_await(watcher: ServiceWatcher, event: HassetteServiceEvent) -> None:
    """Call on_service_running and wait for the spawned readiness task to complete."""
    pending_before = set(watcher.task_bucket.pending_tasks())
    await watcher.on_service_running(event)
    new_tasks = set(watcher.task_bucket.pending_tasks()) - pending_before
    for task in new_tasks:
        await asyncio.wait_for(asyncio.shield(task), timeout=AWAIT_TIMEOUT)


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


async def test_exponential_backoff(watcher: ServiceWatcher):
    """Backoff delay increases exponentially across an episode's attempts (using shutdown-safe sleep)."""
    dummy = register_dummy_service(
        watcher,
        fail_times=ALWAYS_FAIL,
        restart_type=RestartType.TEMPORARY,
        budget_intensity=3,
        backoff_base_seconds=1.0,
        backoff_multiplier=2.0,
        backoff_max_seconds=60.0,
    )

    sleep_calls: list[float] = []

    async def mock_shutdown_safe_sleep(duration: float) -> bool:
        sleep_calls.append(duration)
        return True  # sleep completed normally

    with patch.object(watcher, "shutdown_safe_sleep", side_effect=mock_shutdown_safe_sleep):
        await restart_and_await(watcher, dummy.failed_event)

    # attempt 1: backoff = 1.0 * 2^0 = 1.0
    # attempt 2: backoff = 1.0 * 2^1 = 2.0
    # attempt 3: backoff = 1.0 * 2^2 = 4.0
    assert sleep_calls == [1.0, 2.0, 4.0]


async def test_budget_reset_on_recovery(watcher: ServiceWatcher):
    """Budget resets when a service becomes RUNNING and ready after its restart episode ended."""
    context.PROTECT_TASK.set(False)
    dummy = register_dummy_service(
        watcher,
        fail_times=1,
        restart_type=RestartType.TRANSIENT,
        budget_intensity=5,
        startup_timeout_seconds=1.0,
    )

    # Accumulate 2 restart attempts: the first fails, the second succeeds
    await restart_and_await(watcher, dummy.failed_event)

    assert budget_entries(watcher, dummy.key) == 2

    # Mark the service ready, then fire RUNNING event — budget should reset
    mark_ready(dummy.service, reason="test")
    await on_running_and_await(watcher, make_service_running_event(dummy.service))

    assert budget_entries(watcher, dummy.key) == 0  # budget reset


async def test_budget_reset_when_attempt_succeeds_after_mid_episode_readiness(watcher: ServiceWatcher):
    """A service that is ready by the time a successful attempt's restart() returns gets its budget
    reset by the episode, even though the readiness it signaled mid-attempt was ignored.
    """
    context.PROTECT_TASK.set(False)
    starts = 0
    watcher_ref = watcher

    class _ReadyDuringInit(Service):
        restart_spec: ClassVar[RestartSpec] = make_fast_spec(
            restart_type=RestartType.TRANSIENT, budget_intensity=5, startup_timeout_seconds=1.0
        )

        async def serve(self):
            await asyncio.Event().wait()

        async def on_initialize(self):
            nonlocal starts
            starts += 1
            if starts == 1:
                raise RuntimeError("first attempt fails")
            mark_ready(self, reason="test")

        async def after_initialize(self):
            await on_running_and_await(watcher_ref, make_service_running_event(self))

    service = _ReadyDuringInit(watcher.hassette)
    mark_failed(service)
    watcher.hassette.children.append(service)
    key = watcher.service_key(service.class_name, service.role)

    await restart_and_await(watcher, make_service_failed_event(service))

    assert starts == 2
    assert budget_entries(watcher, key) == 0


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


async def test_in_restart_guard_drops_duplicate_even_when_budget_exhausted(watcher: ServiceWatcher):
    """A FAILED event racing the in-restart guard is always dropped, even if budget is exhausted.

    Budget state alone cannot tell whether a FAILED event arriving while `_restarting` is set
    is the in-flight attempt's own failure or a duplicate/redelivery of the original failure
    that started this attempt -- record_restart() for the current attempt already ran before
    the guard is ever consulted, so is_exhausted() reads the same either way. Treating an
    already-exhausted budget as proof this racing event represents a genuine new failure was
    a false positive: no second failure has actually happened yet. The in-flight attempt's own
    failure is detected directly in execute_restart()'s own exception handler instead (see
    test_execute_restart_own_failure_triggers_exhaustion), which cannot race this guard.
    """
    dummy = register_dummy_service(watcher, restart_type=RestartType.PERMANENT, budget_intensity=1)

    watcher._restarting.add(dummy.key)
    budget = watcher.get_budget(dummy.key, dummy.spec)
    budget.record_restart()
    assert budget.is_exhausted()

    with EventCapture.capturing(watcher.hassette) as capture:
        await watcher.restart_service(dummy.failed_event)

    assert watcher.hassette.fatal_shutdown_reason is None, (
        "A duplicate FAILED event racing the in-restart guard must not trigger exhaustion"
    )
    assert capture.events == [], "Dropped duplicate must not emit any status event"
    assert dummy.key in watcher._restarting, "Guard must remain set -- the in-flight attempt still owns this key"

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


async def test_readiness_timeout_no_budget_impact(watcher: ServiceWatcher):
    """Readiness timeout after RUNNING does NOT increment restart budget."""
    dummy = register_dummy_service(
        watcher,
        restart_type=RestartType.TRANSIENT,
        budget_intensity=5,
        startup_timeout_seconds=0.05,
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
    mark_failed(service_a)
    mark_failed(service_b)

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


async def test_failed_restart_attempt_retries_while_budget_remains(watcher: ServiceWatcher):
    """A restart attempt whose initialize() raises is followed by the next attempt, not abandoned.

    The attempt's own FAILED event arrives while the episode still holds `_restarting`, so the
    in-restart guard drops it; the retry has to come from execute_restart() itself.
    """
    dummy = register_dummy_service(watcher, fail_times=1, restart_type=RestartType.TRANSIENT, budget_intensity=5)

    await restart_and_await(watcher, dummy.failed_event)

    assert dummy.calls["start"] == 2, "The failed first attempt should be followed by exactly one more"
    assert budget_entries(watcher, dummy.key) == 2, "Each attempt counts against the budget exactly once"
    assert dummy.service.status == ResourceStatus.RUNNING
    assert dummy.key not in watcher._restarting, "The episode releases the in-restart guard when it ends"


async def test_failed_restart_attempts_walk_budget_then_exhaust(watcher: ServiceWatcher):
    """One FAILED event drives a service that never initializes through its whole budget, then exhaustion."""
    dummy = register_dummy_service(
        watcher, fail_times=ALWAYS_FAIL, restart_type=RestartType.TEMPORARY, budget_intensity=3
    )

    await restart_and_await(watcher, dummy.failed_event)

    assert dummy.calls["start"] == 3, "Every budgeted attempt should run"
    assert budget_entries(watcher, dummy.key) == 3
    assert dummy.service.status == ResourceStatus.EXHAUSTED_DEAD


async def test_readiness_during_restart_episode_does_not_release_episode_key(watcher: ServiceWatcher):
    """A service that is ready before a post-ready init step fails stays owned by its episode.

    Readiness reached mid-attempt must not reset the budget or release `_restarting`: the attempt
    is still inside restart(), so a release would let the post-ready failure's FAILED event start
    a second episode and let every attempt refill the budget, retrying without bound.
    """
    post_ready_failure_cap = 10  # keeps the test finite if attempts are unbounded
    starts = 0
    watcher_ref = watcher

    class _FailsAfterReady(Service):
        restart_spec: ClassVar[RestartSpec] = make_fast_spec(
            restart_type=RestartType.TEMPORARY, budget_intensity=3, startup_timeout_seconds=1.0
        )

        async def serve(self):
            await asyncio.Event().wait()

        async def on_initialize(self):
            mark_ready(self, reason="test")

        async def after_initialize(self):
            nonlocal starts
            starts += 1
            await on_running_and_await(watcher_ref, make_service_running_event(self))
            if starts > post_ready_failure_cap:
                return
            mark_failed(self)
            await watcher_ref.restart_service(make_service_failed_event(self))
            raise RuntimeError("post-ready init step failed")

    service = _FailsAfterReady(watcher.hassette)
    mark_failed(service)
    watcher.hassette.children.append(service)
    key = watcher.service_key(service.class_name, service.role)

    episodes = 0
    real_execute = watcher.execute_restart

    async def counting_execute(*args: object, **kwargs: object) -> None:
        nonlocal episodes
        episodes += 1
        await real_execute(*args, **kwargs)

    with patch.object(watcher, "execute_restart", side_effect=counting_execute):
        await restart_and_await(watcher, make_service_failed_event(service))

    assert episodes == 1, "A post-ready failure must not start a second restart episode"
    assert starts == 3, "Attempts must stay bounded by the budget even though each one reached ready"
    assert service.status == ResourceStatus.EXHAUSTED_DEAD
    assert key not in watcher._restarting


async def test_late_failed_event_during_exhaustion_does_not_exhaust_twice(watcher: ServiceWatcher):
    """The exhausting attempt's own FAILED event, delivered while handle_exhaustion() is still
    dispatching its status event (service still FAILED), is dropped -- exhaustion runs once.
    """
    dummy = register_dummy_service(
        watcher, fail_times=ALWAYS_FAIL, restart_type=RestartType.TEMPORARY, budget_intensity=1
    )
    real_dispatch = watcher.dispatch_status_event_best_effort
    real_exhaustion = watcher.handle_exhaustion
    exhaustion_calls = 0
    late_event_delivered = False

    async def dispatch_with_late_event(name: str, role: ResourceRole, event: HassetteServiceEvent) -> None:
        nonlocal late_event_delivered
        if not late_event_delivered:
            late_event_delivered = True
            assert dummy.service.status == ResourceStatus.FAILED, "precondition: status not yet moved on"
            await watcher.restart_service(dummy.failed_event)
        await real_dispatch(name, role, event)

    async def counting_exhaustion(*args: object, **kwargs: object) -> None:
        nonlocal exhaustion_calls
        exhaustion_calls += 1
        await real_exhaustion(*args, **kwargs)

    with (
        patch.object(watcher, "dispatch_status_event_best_effort", side_effect=dispatch_with_late_event),
        patch.object(watcher, "handle_exhaustion", side_effect=counting_exhaustion),
    ):
        await restart_and_await(watcher, dummy.failed_event)

    assert late_event_delivered
    assert exhaustion_calls == 1, "A late FAILED event during exhaustion must not run exhaustion again"
    assert dummy.service.status == ResourceStatus.EXHAUSTED_DEAD


async def test_stale_failed_event_dropped_when_service_not_failed(watcher: ServiceWatcher):
    """A FAILED event for a service that is no longer FAILED (recovered, cooling, dead) is stale."""
    dummy = register_dummy_service(watcher, restart_type=RestartType.TRANSIENT, budget_intensity=5)
    dummy.service._status = ResourceStatus.EXHAUSTED_COOLING

    await watcher.restart_service(dummy.failed_event)

    assert dummy.key not in watcher._budgets, "A stale FAILED event must not touch the budget"
    assert dummy.key not in watcher._restarting
    assert dummy.calls["start"] == 0


async def test_bus_recovery_reconciliation(watcher: ServiceWatcher):
    """BusService restarts, another service is in FAILED state during blind window → reconciliation picks it up."""
    dummy = register_dummy_service(watcher, restart_type=RestartType.TRANSIENT, budget_intensity=5)

    # register_dummy_service leaves the service FAILED with no budget entry, as if its FAILED
    # event was dropped during the BusService restart window.
    assert dummy.key not in watcher._budgets  # no budget entry — dropped during blind window

    # Run reconciliation
    await watcher.reconcile_after_bus_recovery()

    # Reconciliation should have picked up the FAILED service and entered restart flow
    assert budget_entries(watcher, dummy.key) == 1, "Reconciliation should have recorded one restart"
