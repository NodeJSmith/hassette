"""Unit tests for AppLifecycleService instance-level lifecycle operations.

Complements test_app_lifecycle_service.py (init/properties/bootstrap-admission/apply-changes
gating), test_app_lifecycle_service_coverage.py (remaining branch coverage), and the
operation-family files: test_app_lifecycle_service_start_stop.py (whole-app start/stop),
test_app_lifecycle_service_per_instance_ops.py (per-instance start/stop/reload and locking),
test_app_lifecycle_service_reload.py (change application and reload), and
test_app_lifecycle_service_reconcile.py (resolve_only_apps/refresh_config/reconcile), and
test_app_lifecycle_service_initialize.py (instance initialization). This file covers
registration removal, walk-away cleanup, and instance/all-app shutdown outcomes.
"""

import asyncio
import re
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from hassette_wire import ResourceStatus

from hassette.core import app_lifecycle_instances
from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.resources.shutdown_deadline import deadline_in
from hassette.resources.shutdown_outcome import ShutdownOutcome, ShutdownResult, incomplete_outcome, merge_outcomes
from hassette.scheduler.classes import Job
from hassette.scheduler.scheduler import Scheduler
from hassette.testing import EventCapture
from hassette.types import Topic
from tests.support.app_registry_helpers import seed_failed
from tests.support.factories import make_mock_parent
from tests.support.helpers import noop
from tests.support.mock_hassette import make_mock_hassette
from tests.support.outcomes import AnyNameOutcomes
from tests.support.task_buckets import sealed_fallback_task_factory

from .conftest import (
    app_state_payloads,
    failure_writes,
    fake_set_status,
    make_mock_app_instance,
    set_registry_apps,
)

if TYPE_CHECKING:
    from hassette.app.app import App


class TestRemoveInstanceRegistrations:
    async def test_bus_cleanup_failure_does_not_skip_scheduler_cleanup(
        self, lifecycle_service: AppLifecycleService, mock_app_instance: AsyncMock
    ) -> None:
        """Bus listener cleanup failure does not prevent scheduler job cleanup."""
        mock_app_instance.bus.remove_all_listeners.side_effect = RuntimeError("bus exploded")

        await lifecycle_service.remove_instance_registrations(mock_app_instance)

        mock_app_instance.scheduler.remove_all_jobs.assert_called_once()

    async def test_manual_job_reaches_removal_not_just_heap_resident_jobs(self) -> None:
        """A manual job (never on the scheduler heap) owned by a walked-away instance must still be removed.

        Uses a real Scheduler (not a mock) so the manual job actually lives only in
        the scheduler's own registry, never on the heap — exactly the case a heap-only
        scan by owner string could not reach.
        Asserting SchedulerService.remove_jobs() was awaited with the manual job proves
        cleanup goes through the same identity-checked, registry-aware path as
        normal shutdown (Scheduler.remove_all_jobs), not the heap-only owner scan.

        Also asserts the removal callback registered by Scheduler.__init__ is
        deregistered afterward — a walked-away instance's Scheduler is discarded for
        good (unlike hassette.testing._reset.reset_scheduler, which reuses its instance), so it
        must explicitly deregister rather than leak the stale callback.
        """
        hassette = make_mock_hassette(sealed=False)

        async def _add_job(job: Job) -> None:
            job.mark_registered(1)

        hassette.scheduler_service.add_job = AsyncMock(side_effect=_add_job)

        scheduler = Scheduler(hassette, parent=make_mock_parent())
        await scheduler.initialize()

        # Manual jobs have no trigger and never touch the heap.
        job = await scheduler.register(noop, name="manual_job")

        registry = MagicMock()
        lifecycle_service = AppLifecycleService(hassette, parent=None, registry=registry)

        inst = MagicMock()
        inst.app_config.instance_name = "walked_away_instance"
        inst.bus.remove_all_listeners = Mock()
        inst.scheduler = scheduler

        await lifecycle_service.remove_instance_registrations(inst)

        hassette.scheduler_service.remove_jobs.assert_awaited_once_with([job])
        hassette.scheduler_service.deregister_removal_callback.assert_called_once_with(scheduler.owner_id)


class TestShutdownInstance:
    async def test_calls_shutdown(self, lifecycle_service: AppLifecycleService, mock_app_instance: AsyncMock) -> None:
        """Calls inst.shutdown()."""
        await lifecycle_service.shutdown_instance(mock_app_instance, outcomes=AnyNameOutcomes())

        mock_app_instance.shutdown.assert_awaited_once()

    # dup-ignore-start: pytest test function signature (see .claude/rules/tests-unit-core.md)
    async def test_catches_exceptions_and_flags_the_instance(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_hassette: MagicMock,
        mock_registry: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        # dup-ignore-end
        """A raised shutdown doesn't raise here: it is FAILED with a failure entry and flagged, since the
        coordinator's stored outcome is INCOMPLETE.
        """
        event_capture.install(mock_hassette)
        error = RuntimeError("Shutdown failed")
        mock_app_instance.shutdown.side_effect = error
        mock_app_instance.shutdown_outcome = incomplete_outcome("app's shutdown coordinator raised RuntimeError")

        await lifecycle_service.shutdown_instance(mock_app_instance, outcomes=AnyNameOutcomes())

        failed_calls = app_state_payloads(event_capture, ResourceStatus.FAILED)
        assert len(failed_calls) == 1
        [write] = failure_writes(mock_registry)
        assert write.kwargs["error"] is error
        assert write.kwargs["needs_restart"] is not None

    async def test_writes_the_outcome_status_only_after_the_teardown(
        self, lifecycle_service: AppLifecycleService, mock_app_instance: AsyncMock, mock_registry: MagicMock
    ) -> None:
        """The instance stays registered through its teardown, so readers see STOPPING rather than a placeholder."""
        order: list[object] = []

        async def teardown() -> ShutdownOutcome:
            order.append("teardown")
            return ShutdownOutcome(ShutdownResult.TIMED_OUT, reason="hook")

        def record_write(*args: object, **kwargs: object) -> object:
            order.append(args[2])
            return fake_set_status(*args, **kwargs)  # pyright: ignore[reportArgumentType]

        mock_app_instance.shutdown = AsyncMock(side_effect=teardown)
        mock_registry.set_status.side_effect = record_write

        await lifecycle_service.shutdown_instance(mock_app_instance, outcomes=AnyNameOutcomes())

        assert order == ["teardown", ResourceStatus.FAILED]

    async def test_emits_stopped_event(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_hassette: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        """Emits HASSETTE_EVENT_APP_STATE_CHANGED with STOPPED status."""
        event_capture.install(mock_hassette)
        await lifecycle_service.shutdown_instance(mock_app_instance, outcomes=AnyNameOutcomes())

        stopped_calls = app_state_payloads(event_capture, ResourceStatus.STOPPED)
        assert len(stopped_calls) == 1


class TestShutdownInstanceEntryDeadline:
    async def test_sets_the_entry_deadline_on_the_instance(
        self, lifecycle_service: AppLifecycleService, mock_app_instance: AsyncMock
    ) -> None:
        """The stop leg runs under one deadline the length of the stop stage, set before shutdown starts."""
        loop = asyncio.get_running_loop()
        before = loop.time()

        await lifecycle_service.shutdown_instance(mock_app_instance, outcomes=AnyNameOutcomes())

        deadline = mock_app_instance._shutdown_deadline
        assert deadline is not None
        assert before < deadline <= loop.time() + lifecycle_service.entry_deadline_seconds

    async def test_a_caller_deadline_only_shortens_the_entry_deadline(
        self, lifecycle_service: AppLifecycleService, mock_app_instance: AsyncMock
    ) -> None:
        """Process exit passes what is left of its stop stage; the instance gets the closer of the two."""
        outer = deadline_in(1.0)

        await lifecycle_service.shutdown_instance(mock_app_instance, deadline=outer, outcomes=AnyNameOutcomes())

        assert mock_app_instance._shutdown_deadline == outer

    # dup-ignore-start: pytest test function signature (see .claude/rules/tests-unit-core.md)
    async def test_walks_away_from_a_stop_that_outlives_its_deadline(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_hassette: MagicMock,
        mock_registry: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        # dup-ignore-end
        """On expiry the instance is force-terminated, its listeners and jobs are removed by owner, and it is
        reported FAILED with a registry failure entry and a needs-restart reason naming the forced terminal.
        """
        event_capture.install(mock_hassette)

        async def hang() -> ShutdownOutcome:
            await asyncio.Event().wait()
            return ShutdownOutcome()

        mock_app_instance.shutdown = AsyncMock(side_effect=hang)
        mock_app_instance._force_terminal = Mock()
        mock_app_instance.shutdown_outcome = incomplete_outcome("app was force-terminated")

        outcome = await asyncio.wait_for(
            lifecycle_service.shutdown_instance(
                mock_app_instance, deadline=deadline_in(0.1), outcomes=AnyNameOutcomes()
            ),
            timeout=5,
        )

        assert outcome is not None
        assert outcome.result is ShutdownResult.INCOMPLETE
        mock_app_instance._force_terminal.assert_called_once()
        mock_app_instance.bus.remove_all_listeners.assert_called_once()
        mock_app_instance.scheduler.remove_all_jobs.assert_called_once()
        [write] = failure_writes(mock_registry)
        assert write.args[:2] == (mock_app_instance.app_key, "test_instance")
        assert isinstance(write.kwargs["error"], TimeoutError)
        reason = write.kwargs["needs_restart"].reason
        assert "timed out" in reason
        assert "app was force-terminated; work may still be running" in reason
        assert len(app_state_payloads(event_capture, ResourceStatus.FAILED)) == 1
        assert app_state_payloads(event_capture, ResourceStatus.STOPPED) == []

    async def test_a_walk_away_whose_cleanup_hangs_still_ends_and_records_the_instance(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_hassette: MagicMock,
        mock_registry: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Removing a walked-away instance's registrations is bounded by ``WALK_AWAY_CLEANUP_TIMEOUT_SECONDS``,
        so a wedged scheduler can't hold the stop past its deadline.
        """
        monkeypatch.setattr(app_lifecycle_instances, "WALK_AWAY_CLEANUP_TIMEOUT_SECONDS", 0.1)

        async def hang(*_args, **_kwargs) -> ShutdownOutcome:
            await asyncio.Event().wait()
            return ShutdownOutcome()

        mock_app_instance.shutdown = AsyncMock(side_effect=hang)
        mock_app_instance._force_terminal = Mock()
        mock_app_instance.scheduler.remove_all_jobs = AsyncMock(side_effect=hang)

        await asyncio.wait_for(
            lifecycle_service.shutdown_instance(
                mock_app_instance, deadline=deadline_in(0.1), outcomes=AnyNameOutcomes()
            ),
            timeout=5,
        )

        mock_app_instance._force_terminal.assert_called_once()
        assert len(failure_writes(mock_registry)) == 1

    # dup-ignore-start: pytest test function signature (see .claude/rules/tests-unit-core.md)
    async def test_a_timed_out_hook_reports_failed_without_walking_away(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_hassette: MagicMock,
        mock_registry: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        # dup-ignore-end
        """A stop that finished but whose hook was cut off at its bound is FAILED with a registry entry."""
        event_capture.install(mock_hassette)
        mock_app_instance.shutdown = AsyncMock(return_value=ShutdownOutcome(ShutdownResult.TIMED_OUT, reason="hook"))
        mock_app_instance._force_terminal = Mock()

        await lifecycle_service.shutdown_instance(mock_app_instance, outcomes=AnyNameOutcomes())

        mock_app_instance._force_terminal.assert_not_called()
        [write] = failure_writes(mock_registry)
        assert isinstance(write.kwargs["error"], TimeoutError)
        assert write.kwargs.get("needs_restart") is None
        assert len(app_state_payloads(event_capture, ResourceStatus.FAILED)) == 1

    async def test_a_timed_out_hook_with_incomplete_evidence_is_worded_by_its_reason(
        self, lifecycle_service: AppLifecycleService, mock_app_instance: AsyncMock, mock_registry: MagicMock
    ) -> None:
        """A stop whose hook timed out and whose evidence is also incomplete is INCOMPLETE: it is FAILED and
        flagged, worded "stopped, but…" with the reason naming the step, not "timed out".
        """
        outcome = merge_outcomes(
            ShutdownOutcome(ShutdownResult.TIMED_OUT, reason="app: shutdown hook on_shutdown timed out after 5s"),
            incomplete_outcome("app's shutdown body raised RuntimeError"),
        )
        mock_app_instance.shutdown = AsyncMock(return_value=outcome)

        await lifecycle_service.shutdown_instance(mock_app_instance, outcomes=AnyNameOutcomes())

        [write] = failure_writes(mock_registry)
        assert not isinstance(write.kwargs["error"], TimeoutError)
        reason = write.kwargs["needs_restart"].reason
        assert reason == "stopped, but app's shutdown body raised RuntimeError; work may still be running"

    @pytest.mark.parametrize(
        ("result", "hook_reason", "expected_pattern"),
        [
            (
                ShutdownResult.TIMED_OUT,
                "app: shutdown hook on_shutdown timed out after 5s",
                r"stop timed out after .+; app: shutdown hook on_shutdown timed out after 5s; "
                r"work is still running: app:poller",
            ),
            (
                ShutdownResult.FAILED,
                "app: a shutdown hook raised RuntimeError",
                r"stopped, but app: a shutdown hook raised RuntimeError; work is still running: app:poller",
            ),
        ],
    )
    async def test_a_hook_that_left_tasks_behind_is_named_in_the_needs_restart_reason(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_registry: MagicMock,
        result: ShutdownResult,
        hook_reason: str,
        expected_pattern: str,
    ) -> None:
        """A restart-unsafe FAILED or TIMED_OUT outcome names the hook behind it, not only the tasks left running."""
        outcome = ShutdownOutcome(result, ("app:poller",), hook_reason)
        mock_app_instance.shutdown = AsyncMock(return_value=outcome)

        await lifecycle_service.shutdown_instance(mock_app_instance, outcomes=AnyNameOutcomes())

        reason = failure_writes(mock_registry)[0].kwargs["needs_restart"].reason
        assert re.fullmatch(expected_pattern, reason), reason

    # dup-ignore-start: pytest test function signature (see .claude/rules/tests-unit-core.md)
    async def test_a_stop_that_left_tasks_pending_is_failed_and_flagged_without_timing_out(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_hassette: MagicMock,
        mock_registry: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        # dup-ignore-end
        """A stop that finished in time but left work running is FAILED and flagged, not STOPPED."""
        event_capture.install(mock_hassette)
        mock_app_instance.shutdown = AsyncMock(return_value=ShutdownOutcome(still_running=("app:poller",)))

        await lifecycle_service.shutdown_instance(mock_app_instance, outcomes=AnyNameOutcomes())

        [write] = failure_writes(mock_registry)
        assert write.args[:2] == ("test_app", "test_instance")
        assert not isinstance(write.kwargs["error"], TimeoutError)
        assert "app:poller" in str(write.kwargs["error"])
        assert write.kwargs["needs_restart"].pending_tasks == ("app:poller",)
        assert app_state_payloads(event_capture, ResourceStatus.STOPPED) == []
        assert len(app_state_payloads(event_capture, ResourceStatus.FAILED)) == 1

    async def test_a_failed_outcome_event_is_logged_not_recorded_twice(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_hassette: MagicMock,
        mock_registry: MagicMock,
    ) -> None:
        """The outcome is written before its event; a send failure doesn't re-write it or re-flag it."""
        mock_app_instance.shutdown = AsyncMock(return_value=ShutdownOutcome(still_running=("app:poller",)))
        mock_hassette.send_event = AsyncMock(side_effect=RuntimeError("event bus down"))

        outcome = await lifecycle_service.shutdown_instance(mock_app_instance, outcomes=AnyNameOutcomes())

        assert outcome is not None
        assert outcome.still_running == ("app:poller",)
        [write] = failure_writes(mock_registry)
        assert write.kwargs["needs_restart"] is not None

    # dup-ignore-start: pytest test function signature (see .claude/rules/tests-unit-core.md)
    async def test_a_raised_hook_still_reports_stopped(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_hassette: MagicMock,
        mock_registry: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        # dup-ignore-end
        """Only a timed-out stop is FAILED here; a hook that raised is evidence on the outcome, not a timeout."""
        event_capture.install(mock_hassette)
        mock_app_instance.shutdown = AsyncMock(return_value=ShutdownOutcome(ShutdownResult.FAILED, reason="hook"))

        await lifecycle_service.shutdown_instance(mock_app_instance, outcomes=AnyNameOutcomes())

        assert failure_writes(mock_registry) == []
        assert len(app_state_payloads(event_capture, ResourceStatus.STOPPED)) == 1


class TestShutdownInstances:
    async def test_empty_list_returns_early(self, lifecycle_service: AppLifecycleService) -> None:
        """Returns early for no instances."""
        await lifecycle_service.shutdown_instances([], outcomes=AnyNameOutcomes())

    async def test_stops_instances_concurrently(self, lifecycle_service: AppLifecycleService) -> None:
        """No instance's hooks wait on another's: two slow stops take about as long as one."""
        stop_seconds = 0.3

        async def slow_stop() -> ShutdownOutcome:
            await asyncio.sleep(stop_seconds)
            return ShutdownOutcome()

        instances = []
        for idx in range(2):
            inst = make_mock_app_instance(instance_name=f"inst_{idx}")
            inst.shutdown = AsyncMock(side_effect=slow_stop)
            instances.append(inst)

        loop = asyncio.get_running_loop()
        start = loop.time()
        await lifecycle_service.shutdown_instances(instances, outcomes=AnyNameOutcomes())
        elapsed = loop.time() - start

        assert elapsed < stop_seconds * 2, f"instances stopped one after another ({elapsed:.2f}s)"

    async def test_a_raising_stop_waits_for_its_siblings_before_raising(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """A stop that raises doesn't leave its sibling stops running detached."""
        finished: list[str] = []

        async def slow_stop() -> ShutdownOutcome:
            await asyncio.sleep(0.1)
            finished.append("inst_1")
            return ShutdownOutcome()

        mocks = [make_mock_app_instance(instance_name=f"inst_{idx}") for idx in range(2)]
        mocks[1].shutdown = AsyncMock(side_effect=slow_stop)
        instances: list[App] = list(mocks)
        first_write = [True]

        def raise_first(*args: object, **kwargs: object) -> object:
            if first_write.pop() if first_write else False:
                raise RuntimeError("registry write failed")
            return fake_set_status(*args, **kwargs)  # pyright: ignore[reportArgumentType]

        mock_registry.set_status.side_effect = raise_first

        with pytest.raises(RuntimeError, match="registry write failed"):
            await lifecycle_service.shutdown_instances(instances, outcomes=AnyNameOutcomes())

        assert finished == ["inst_1"]

    async def test_calls_shutdown_for_each(self, lifecycle_service: AppLifecycleService) -> None:
        """Calls shutdown for each app instance."""
        app1 = make_mock_app_instance(instance_name="app1")
        app1.status = ResourceStatus.RUNNING
        app2 = make_mock_app_instance(instance_name="app2")
        app2.status = ResourceStatus.RUNNING

        instances: list[App] = [app1, app2]

        await lifecycle_service.shutdown_instances(instances, outcomes=AnyNameOutcomes())

        app1.shutdown.assert_awaited_once()
        app2.shutdown.assert_awaited_once()

    async def test_emits_stopping_event(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_hassette: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        """Emits STOPPING event for each instance before shutting down."""
        event_capture.install(mock_hassette)
        mock_app_instance.status = ResourceStatus.RUNNING
        instances: list[App] = [mock_app_instance]

        await lifecycle_service.shutdown_instances(instances, outcomes=AnyNameOutcomes())

        first_event = event_capture.events[0]
        assert first_event.topic == Topic.HASSETTE_EVENT_APP_STATE_CHANGED
        assert first_event.payload.data.status == ResourceStatus.STOPPING


class TestShutdownAll:
    async def test_shuts_down_all_registered_apps(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """Calls shutdown for each app in registry."""
        app1 = make_mock_app_instance(instance_name="app1")
        app1.status = ResourceStatus.RUNNING
        app2 = make_mock_app_instance(instance_name="app2")
        app2.status = ResourceStatus.RUNNING

        set_registry_apps(mock_registry, {"app1": {"app1": app1}, "app2": {"app2": app2}})

        await lifecycle_service.shutdown_all()

        app1.shutdown.assert_awaited_once()
        app2.shutdown.assert_awaited_once()

    async def test_stops_apps_when_the_loops_fallback_bucket_is_sealed(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """App stops still run at exit, when the root's sealed TaskBucket is the loop's task-factory fallback."""
        app1 = make_mock_app_instance(instance_name="app1")
        app2 = make_mock_app_instance(instance_name="app2")
        set_registry_apps(mock_registry, {"app1": {"app1": app1}, "app2": {"app2": app2}})

        with sealed_fallback_task_factory():
            await lifecycle_service.shutdown_all()

        app1.shutdown.assert_awaited_once()
        app2.shutdown.assert_awaited_once()

    async def test_clears_registry(self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock) -> None:
        """Calls registry.clear_all() after shutdown."""
        set_registry_apps(mock_registry, {})

        await lifecycle_service.shutdown_all()

        mock_registry.clear_all.assert_called_once()

    async def test_sends_no_event_for_entries_it_clears(
        self, real_registry_service: AppLifecycleService, mock_hassette: MagicMock, event_capture: EventCapture
    ) -> None:
        """The registry reset at exit is raw: failures still standing get no closing event (spec 154 D7)."""
        event_capture.install(mock_hassette)
        registry = real_registry_service.registry
        seed_failed(registry, "test_app", "failed", ValueError("boom"))
        seed_failed(registry, "test_app", "flagged", ValueError("hung"), needs_restart="work still running")

        await real_registry_service.shutdown_all()

        assert event_capture.payloads(Topic.HASSETTE_EVENT_APP_STATE_CHANGED) == []
        assert registry.get_instances("test_app") == {}
