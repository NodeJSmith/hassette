"""Integration tests for ServiceWatcher restart logic.

Tests use RestartSpec-based per-service configuration rather than global config fields.
"""

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Callable
from typing import ClassVar, NamedTuple
from unittest.mock import patch

import pytest

from hassette import HassetteConfig, context
from hassette.core.service_watcher import ServiceWatcher
from hassette.events import Event, HassetteServiceEvent
from hassette.events.base import HassettePayload
from hassette.events.hassette import ServiceStatusPayload
from hassette.resources.lifecycle import mark_ready
from hassette.resources.restart import RestartSpec
from hassette.resources.service import Service
from hassette.testing import EventCapture, HassetteHarness, build_harness, wait_for
from hassette.testing._reset import reset_hassette_lifecycle
from hassette.types import ResourceStatus, Topic
from hassette.types.enums import RestartType
from tests.support.harness import preserve_config
from tests.support.helpers import make_service_failed_event, make_service_running_event

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
async def watcher(hassette_with_bus, request: pytest.FixtureRequest) -> ServiceWatcher:
    """Return a fresh service watcher for each test.

    Deliberately a *plain* async fixture (no ``yield``) with cleanup registered via
    ``request.addfinalizer()`` as a *synchronous* callback, mirroring
    ``tests/integration/conftest.py::hassette_instance`` (see its docstring for the full
    mechanism). This file specifically exercises restart-budget exhaustion, which calls
    ``hassette.shutdown()`` and seals the shared ``hassette_with_bus`` harness's root
    TaskBucket mid-test. If teardown were a ``yield``-based async generator, pytest-asyncio's
    resumption of it would need to create a brand-new Task via the loop's task factory --
    which, while that factory still routes through the now-sealed bucket, raises immediately,
    before this fixture's own cleanup (``watcher.shutdown()`` /
    ``reset_hassette_lifecycle()``) ever runs, and leaves the loop poisoned for the rest of
    the pytest-xdist worker's session.

    Also sets context.PROTECT_TASK, so this test's own top-level task is never tracked by any
    TaskBucket in the first place (see hassette.context.PROTECT_TASK for the full mechanism).
    Restart-budget exhaustion drives a real hassette.shutdown(), whose cancel_all() would
    otherwise cancel this test's own task as a side effect purely because pytest-asyncio's task
    creation for it happened to be routed through the same loop's factory with no other bucket
    claimed -- the same "no active scope" signal a genuinely rogue task also produces, and the
    only thing that distinguishes them is this deliberate opt-in. A bare `.set()` (not a scoped
    context manager) is required: this fixture's own task finishes before the test body's task
    is even created, and pytest-asyncio's own contextvar-propagation machinery is what carries
    the value forward from here into that later task -- see PROTECT_TASK's docstring.
    """
    context.PROTECT_TASK.set(True)
    hassette = hassette_with_bus.hassette
    watcher = ServiceWatcher(hassette, parent=hassette)
    original_children = list(hassette.children)
    config_cm = preserve_config(hassette.config)
    config_cm.__enter__()

    loop = asyncio.get_running_loop()
    safe_task_factory = hassette_with_bus._previous_task_factory

    def _teardown() -> None:
        # Order matters: restore a safe (non-bucket-routed) task factory *before* anything
        # that might create a new Task, including run_until_complete()'s own
        # ensure_future() call. Only swap away from the currently-active factory when the
        # root TaskBucket it routes to is actually sealed (e.g. this test triggered a full
        # hassette.shutdown()) -- most tests never seal it, and unconditionally swapping to
        # the harness's pre-install factory would needlessly drop bucket routing for the
        # cleanup calls below.
        was_sealed = hassette.task_bucket.is_sealed
        if was_sealed:
            loop.set_task_factory(safe_task_factory)
        try:
            # Clean up bus listeners registered by this watcher via propagation
            loop.run_until_complete(watcher.shutdown())
            # reset_hassette_lifecycle() only clears a shutdown *request* that hasn't started
            # a teardown attempt yet -- it explicitly refuses (RuntimeError) to touch an
            # instance with an active shutdown task or a stored teardown report, and refuses
            # a fortiori once event streams are closed by a completed shutdown (see its
            # docstring and `_reject_if_active_or_reported()` in
            # `hassette.test_utils.reset`). A test that lets a PERMANENT service exhaust its
            # restart budget (e.g. test_always_failing_service_stops_after_max_attempts)
            # causes ServiceWatcher to trigger a real, completed `hassette.shutdown()` --
            # reset is not possible in that case, and the shared `hassette_with_bus` harness
            # is genuinely no longer reusable for the rest of this module regardless.
            already_shut_down = (
                hassette.event_streams_closed
                or hassette._shutdown_task is not None
                or hassette._teardown_report is not None
            )
            if not already_shut_down:
                loop.run_until_complete(reset_hassette_lifecycle(hassette, original_children=original_children))
        finally:
            config_cm.__exit__(None, None, None)
            # Do NOT restore active_task_factory here: it routes through hassette.task_bucket,
            # which -- once was_sealed is true -- is permanently sealed for the rest of this
            # module's shared hassette_with_bus harness (a real, completed shutdown is not
            # reversible; see the already_shut_down branch above). Restoring it anyway would
            # route the *next* test's own setup (constructing its ServiceWatcher, etc.) back
            # through the dead bucket, which immediately rejects that work with "TaskBucket(...)
            # is sealed and rejected new work: setup" -- breaking the next test before its body
            # even starts. Leaving safe_task_factory in place is correct for the rest of the
            # module: nothing legitimate can route through the sealed bucket again regardless.

    # PT021: request.addfinalizer() instead of `yield` is deliberate here -- see the
    # docstring above for why a `yield`-based async-generator fixture deadlocks here.
    request.addfinalizer(_teardown)  # noqa: PT021
    return watcher


@contextlib.asynccontextmanager
async def isolated_watcher(
    test_config_class: type[HassetteConfig], unused_tcp_port_factory: "Callable[[], int]"
) -> AsyncIterator[ServiceWatcher]:
    """Build a fresh, private Hassette instance for a single test and yield its ServiceWatcher.

    Some tests in this file drive a real, complete ``hassette.shutdown()`` (restart-budget
    exhaustion or a fatal error). ``reset_hassette_lifecycle()`` correctly refuses to revive an
    instance that has already fully shut down (see KI-004 in
    ``design/specs/105-teardown-restart-safety/known-issues.md``), so those tests cannot share
    the module-scoped ``watcher`` fixture's ``hassette_with_bus`` instance with the rest of this
    file -- running the file in its normal order left one dead shared instance behind for every
    test that followed the first one to trigger shutdown.

    Builds its own ``HassetteConfig`` instance (via the ``test_config_class`` factory, the same
    ``TestConfig`` subclass ``test_config`` itself is built from) rather than reusing the
    session-scoped ``test_config`` object that ``hassette_with_bus`` is already live on for the
    rest of this file. ``build_harness()``'s own teardown calls ``config.reload()``, which fully
    re-runs the config's ``__init__`` in place -- sharing an object with a harness that is still
    alive for the rest of the module would reset that harness's live config out from under it
    mid-file. Constructs ``HassetteHarness`` directly (not via the module-scoped
    ``hassette_harness`` factory fixture) with ``skip_global_set=True``: the module-scoped
    ``hassette_with_bus`` harness has already claimed the process-global "current Hassette"
    contextvar for the whole file, and only one harness may hold it at a time.

    Uses ``build_harness()`` directly inside the test body (not as a ``yield``-based pytest
    fixture), per its own docstring: ``__aexit__`` then runs inline in the test's own
    already-running Task, so there's no risk of pytest-asyncio resuming teardown as a *new* Task
    on the loop after this harness's own task factory has sealed shut -- see
    ``_start_module_harness()``'s docstring in ``hassette.test_utils.fixtures`` for why that
    matters specifically for ``yield``-based *fixtures* shared across a session-scoped loop.

    Unlike the shared ``watcher`` fixture, no ``context.PROTECT_TASK`` is needed here:
    ``build_harness()`` installs its task factory from *inside* this test's own already-running
    task -- i.e., strictly after that task was created -- so the factory can never retroactively
    claim it. ``make_task_factory()`` only ever registers tasks it is asked to *create*
    (``hassette.task_bucket.task_bucket.make_task_factory``); it has no path back to a task that
    already existed before the factory was installed. So even a real ``hassette.shutdown()`` ->
    ``cancel_all()`` here can never reach this test's own task.
    """
    config = test_config_class(web_api={"port": unused_tcp_port_factory()})
    harness = HassetteHarness(config, unused_tcp_port=unused_tcp_port_factory(), skip_global_set=True)
    async with build_harness(harness.with_bus()) as harness:
        hassette = harness.hassette
        watcher = ServiceWatcher(hassette, parent=hassette)
        try:
            yield watcher
        finally:
            await watcher.shutdown()


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


def get_refusing_dummy_service(
    called: dict[str, int],
    hassette,
    *,
    refuse_after: int = 1,
    restart_spec: RestartSpec | None = None,
) -> Service:
    """A Service whose ``on_shutdown`` hook raises starting on the ``refuse_after``-th call
    (1-indexed), producing ``TeardownCause.SHUTDOWN_HOOK_FAILED`` evidence -- a restart-unsafe
    teardown report -- so ``restart()`` raises ``RestartRefusedError`` from that call onward.

    ``refuse_after=1`` (the default) refuses on every restart attempt, for tests that only need
    the very first restart to hit refusal. A caller driving a service through a normal restart
    (or budget exhaustion) before forcing refusal on a later, post-cooldown attempt passes a
    higher value.
    """
    spec = restart_spec if restart_spec is not None else RestartSpec()

    class _Refusing(Service):
        """Restarts cleanly until on_shutdown call number `refuse_after`, then always refuses."""

        restart_spec: ClassVar[RestartSpec] = spec

        async def serve(self):
            await asyncio.Event().wait()

        async def on_shutdown(self):
            called["cancel"] += 1
            if called["cancel"] >= refuse_after:
                raise RuntimeError("shutdown hook fails from this call onward")

        async def on_initialize(self):
            called["start"] += 1

    return _Refusing(hassette)


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
    context.PROTECT_TASK.set(False)
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


async def test_fatal_error_records_fatal_reason(
    test_config_class: type[HassetteConfig], unused_tcp_port_factory: "Callable[[], int]"
):
    """A service raising a configured fatal error records _fatal_shutdown_reason synchronously."""
    async with isolated_watcher(test_config_class, unused_tcp_port_factory) as watcher:
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


async def test_fatal_error_triggers_immediate_shutdown(
    test_config_class: type[HassetteConfig], unused_tcp_port_factory: "Callable[[], int]"
):
    """Service with fatal_error_names: matching exception triggers immediate shutdown, no restart."""
    async with isolated_watcher(test_config_class, unused_tcp_port_factory) as watcher:
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
    context.PROTECT_TASK.set(False)
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


def crashed_events(events: "list[Event]") -> "list[Event]":
    """Filter EventCapture output down to CRASHED service-status events."""
    return [
        e
        for e in events
        if e.topic == Topic.HASSETTE_EVENT_SERVICE_STATUS and e.payload.data.status == ResourceStatus.CRASHED
    ]


async def test_restart_refused_during_backoff_escalates_to_fatal_shutdown(
    test_config_class: type[HassetteConfig], unused_tcp_port_factory: "Callable[[], int]"
):
    """A RestartRefusedError raised from restart() inside execute_restart() (the immediate
    backoff+restart path) is caught and escalated through handle_restart_refused(): one fatal
    reason, one root shutdown request, exactly one CRASHED event, and no retry.
    """
    async with isolated_watcher(test_config_class, unused_tcp_port_factory) as watcher:
        hassette = watcher.hassette
        calls = make_call_counts()
        spec = make_fast_spec(restart_type=RestartType.TRANSIENT, budget_intensity=5)
        # refuse_after=1: the very first restart attempt refuses.
        service = get_refusing_dummy_service(calls, hassette, refuse_after=1, restart_spec=spec)
        hassette.children.append(service)
        failed_event = make_service_failed_event(service)

        assert hassette.fatal_shutdown_reason is None

        with EventCapture.capturing(hassette) as capture:
            await restart_and_await(watcher, failed_event)

        # One fatal reason, naming the refused service, and root shutdown requested.
        assert hassette.fatal_shutdown_reason is not None
        assert service.class_name in hassette.fatal_shutdown_reason
        assert hassette.shutdown_event.is_set()

        # Exactly one CRASHED event, carrying the refusal's exception fields.
        events = crashed_events(capture.events)
        assert len(events) == 1
        assert events[0].payload.data.resource_name == service.class_name
        assert events[0].payload.data.exception_type == "RestartRefusedError"
        assert events[0].payload.data.exception is not None
        assert service.class_name in events[0].payload.data.exception

        # restart() (and thus on_shutdown) was attempted exactly once -- no retry after refusal.
        assert calls["cancel"] == 1
        assert calls["start"] == 0, "initialize() must not run after a refused shutdown"

        # A duplicate trigger after the handler returns: no second CRASHED event or recovery.
        with EventCapture.capturing(hassette) as capture2:
            await watcher.restart_service(failed_event)
        assert capture2.events == []
        assert calls == {"cancel": 1, "start": 0}


async def test_restart_refused_during_cooldown_escalates_to_fatal_shutdown(
    test_config_class: type[HassetteConfig], unused_tcp_port_factory: "Callable[[], int]"
):
    """A RestartRefusedError raised from restart() inside cooldown_and_retry() (the TRANSIENT
    post-cooldown restart path) is caught and escalated the same way as the backoff path: one
    fatal reason, one root shutdown request, exactly one CRASHED event, and no retry.
    """
    async with isolated_watcher(test_config_class, unused_tcp_port_factory) as watcher:
        hassette = watcher.hassette
        calls = make_call_counts()
        spec = make_fast_spec(
            restart_type=RestartType.TRANSIENT,
            budget_intensity=1,
            cooldown_seconds=0.01,
            max_cooldown_cycles=0,
        )
        # refuse_after=2: the first restart (which consumes the one budget slot) succeeds
        # cleanly; the second on_shutdown call -- the post-cooldown restart attempt -- refuses.
        service = get_refusing_dummy_service(calls, hassette, refuse_after=2, restart_spec=spec)
        hassette.children.append(service)
        failed_event = make_service_failed_event(service)
        key = watcher.service_key(service.class_name, service.role)

        # First restart succeeds cleanly, consuming the one budget slot.
        await restart_and_await(watcher, failed_event)
        assert calls == {"cancel": 1, "start": 1}
        assert hassette.fatal_shutdown_reason is None

        # Second FAILED event exceeds budget (intensity=1) -> TRANSIENT cooldown scheduled.
        with EventCapture.capturing(hassette) as capture:
            await watcher.restart_service(failed_event)
            cooldown_task = watcher._cooldown_tasks[key]
            await asyncio.wait_for(asyncio.shield(cooldown_task), timeout=AWAIT_TIMEOUT)

        assert hassette.fatal_shutdown_reason is not None
        assert service.class_name in hassette.fatal_shutdown_reason
        assert hassette.shutdown_event.is_set()

        events = crashed_events(capture.events)
        assert len(events) == 1
        assert events[0].payload.data.resource_name == service.class_name
        assert events[0].payload.data.exception_type == "RestartRefusedError"

        # restart() was attempted exactly once during cooldown (on_shutdown call #2) -- no retry,
        # and initialize() never ran for that refused attempt.
        assert calls == {"cancel": 2, "start": 1}


async def test_restart_refusal_shutdown_survives_event_dispatch_failure(
    test_config_class: type[HassetteConfig], unused_tcp_port_factory: "Callable[[], int]"
):
    """A broken event bus (send_event raising) must not prevent the fatal reason or the root
    shutdown request -- event dispatch is telemetry, not the control path.
    """
    async with isolated_watcher(test_config_class, unused_tcp_port_factory) as watcher:
        hassette = watcher.hassette
        calls = make_call_counts()
        spec = make_fast_spec(restart_type=RestartType.TRANSIENT, budget_intensity=5)
        service = get_refusing_dummy_service(calls, hassette, refuse_after=1, restart_spec=spec)
        hassette.children.append(service)
        failed_event = make_service_failed_event(service)

        with patch.object(hassette, "send_event", side_effect=RuntimeError("bus dead")):
            await restart_and_await(watcher, failed_event)

        assert hassette.fatal_shutdown_reason is not None
        assert service.class_name in hassette.fatal_shutdown_reason
        assert hassette.shutdown_event.is_set()
