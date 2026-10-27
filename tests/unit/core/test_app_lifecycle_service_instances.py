"""Unit tests for AppLifecycleService instance-level lifecycle operations.

Complements test_app_lifecycle_service.py (init/properties/bootstrap-admission/apply-changes
gating), test_app_lifecycle_service_coverage.py (remaining branch coverage), and the
operation-family files: test_app_lifecycle_service_start_stop.py (whole-app start/stop),
test_app_lifecycle_service_per_instance_ops.py (per-instance start/stop/reload and locking),
test_app_lifecycle_service_reload.py (change application and reload), and
test_app_lifecycle_service_reconcile.py (resolve_only_apps/refresh_config/reconcile). This
file covers instance initialization (including failed-init shutdown), walk-away cleanup, and
instance/all-app shutdown outcomes.
"""

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, Mock, call, patch

import pytest
from hassette_wire import ResourceStatus

from hassette.core import app_lifecycle_instances
from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.resources.shutdown_deadline import deadline_in
from hassette.resources.teardown import TeardownCause, TeardownReport
from hassette.scheduler.classes import Job
from hassette.scheduler.scheduler import Scheduler
from hassette.testing import EventCapture
from hassette.types import Topic
from tests.support.factories import make_mock_parent
from tests.support.helpers import noop
from tests.support.mock_hassette import make_mock_hassette
from tests.support.task_buckets import sealed_fallback_task_factory

from .conftest import app_state_payloads, make_mock_app_instance, set_registry_apps

if TYPE_CHECKING:
    from hassette.app.app import App


class TestInitializeInstances:
    async def test_success_calls_initialize_and_mark_ready(
        self, lifecycle_service: AppLifecycleService, mock_app_instance: AsyncMock, mock_manifest: MagicMock
    ) -> None:
        """Calls initialize() and mark_ready() on each instance."""
        instances: dict[int, App] = {0: mock_app_instance}

        with patch("hassette.core.app_lifecycle_instances.mark_ready") as mock_mark_ready:
            await lifecycle_service.initialize_instances("test_app", instances, mock_manifest)

        mock_app_instance.initialize.assert_awaited_once()
        mock_mark_ready.assert_called_once_with(mock_app_instance, reason="initialized")

    async def test_multiple_instances(self, lifecycle_service: AppLifecycleService, mock_manifest: MagicMock) -> None:
        """Initializes all provided instances."""
        app1 = make_mock_app_instance(instance_name="instance_0", class_name="TestApp")
        app2 = make_mock_app_instance(instance_name="instance_1", class_name="TestApp")
        instances: dict[int, App] = {0: app1, 1: app2}

        with patch("hassette.core.app_lifecycle_instances.mark_ready") as mock_mark_ready:
            await lifecycle_service.initialize_instances("test_app", instances, mock_manifest)

        app1.initialize.assert_awaited_once()
        app2.initialize.assert_awaited_once()
        assert mock_mark_ready.call_args_list == [
            call(app1, reason="initialized"),
            call(app2, reason="initialized"),
        ]

    @pytest.mark.parametrize("error", [TimeoutError("Timed out"), ValueError("Init failed")], ids=["timeout", "raise"])
    async def test_failed_init_shuts_the_instance_down_and_records_failure(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_manifest: MagicMock,
        mock_registry: MagicMock,
        error: Exception,
    ) -> None:
        """A failed or timed-out init shuts the instance down with its own hooks skipped, then records the
        init exception as its failure.
        """
        mock_app_instance.initialize.side_effect = error
        instances: dict[int, App] = {0: mock_app_instance}

        await lifecycle_service.initialize_instances("test_app", instances, mock_manifest)

        mock_app_instance.shutdown.assert_awaited_once()
        assert mock_app_instance._skip_own_shutdown_hooks is True
        mock_registry.unregister_app.assert_called_once_with("test_app", 0)
        mock_registry.record_failure.assert_called_once_with("test_app", 0, error)
        mock_registry.flag_needs_restart.assert_not_called()

    async def test_failed_init_whose_work_may_still_run_is_flagged(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_manifest: MagicMock,
        mock_registry: MagicMock,
    ) -> None:
        """An init whose teardown left its initializer pending is FAILED and flagged needs-restart."""
        mock_app_instance.initialize.side_effect = TimeoutError("Timed out")
        mock_app_instance.shutdown = AsyncMock(
            return_value=TeardownReport(causes=(TeardownCause.INITIALIZATION_TASK_PENDING,))
        )
        instances: dict[int, App] = {0: mock_app_instance}

        await lifecycle_service.initialize_instances("test_app", instances, mock_manifest)

        mock_registry.flag_needs_restart.assert_called_once()
        assert mock_registry.flag_needs_restart.call_args.args == ("test_app", 0)

    async def test_failed_init_event_is_failed_from_starting(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_manifest: MagicMock,
        mock_hassette: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        """No STOPPING event is sent for a failed init; its FAILED event comes from STARTING."""
        event_capture.install(mock_hassette)
        mock_app_instance.initialize.side_effect = ValueError("boom")

        await lifecycle_service.initialize_instances("test_app", {0: mock_app_instance}, mock_manifest)

        assert app_state_payloads(event_capture, ResourceStatus.STOPPING) == []
        failed = app_state_payloads(event_capture, ResourceStatus.FAILED)
        assert [p.previous_status for p in failed] == [ResourceStatus.STARTING]

    async def test_a_failed_running_event_is_logged_and_the_app_keeps_running(
        self,
        lifecycle_service: AppLifecycleService,
        mock_manifest: MagicMock,
        mock_hassette: MagicMock,
        mock_registry: MagicMock,
    ) -> None:
        """A failure to send the RUNNING event is a telemetry failure: the app isn't shut down and its
        siblings still initialize.
        """
        app0 = make_mock_app_instance(instance_name="instance_0")
        app1 = make_mock_app_instance(instance_name="instance_1")
        mock_hassette.send_event = AsyncMock(side_effect=RuntimeError("bus closed"))

        await lifecycle_service.initialize_instances("test_app", {0: app0, 1: app1}, mock_manifest)

        app0.shutdown.assert_not_awaited()
        app1.initialize.assert_awaited_once()
        mock_registry.record_failure.assert_not_called()

    async def test_exception_traceback_shows_app_frame_not_just_call_site(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_manifest: MagicMock,
    ) -> None:
        """Logged traceback includes the app's own deep frame, not just outer call-site frames.

        ``get_short_traceback`` treats a positive limit as "closest to the call site" and a
        negative limit as "closest to the raise" (stdlib ``traceback.format_exc`` semantics).
        Init failures are logged with a limit sized for a nested on_initialize() call chain
        specifically so the app author's own raising line is visible, not just framework
        frames near ``anyio.fail_after`` — so the traceback limit must be negative.
        """

        async def level_5():
            raise ValueError("app bug at level 5")

        async def level_4():
            await level_5()

        async def level_3():
            await level_4()

        async def level_2():
            await level_3()

        async def level_1():
            await level_2()

        mock_app_instance.initialize.side_effect = level_1
        instances: dict[int, App] = {0: mock_app_instance}

        with patch.object(lifecycle_service, "logger") as mock_logger:
            await lifecycle_service.initialize_instances("test_app", instances, mock_manifest)

        traceback_arg = mock_logger.error.call_args[0][-1]
        assert "level_5" in traceback_arg

    async def test_continues_after_failure(
        self, lifecycle_service: AppLifecycleService, mock_manifest: MagicMock, mock_registry: MagicMock
    ) -> None:
        """Initializes remaining instances after one fails."""
        app1 = make_mock_app_instance(instance_name="instance_0", class_name="TestApp")
        app1.initialize = AsyncMock(side_effect=ValueError("Failed"))

        app2 = make_mock_app_instance(instance_name="instance_1", class_name="TestApp")

        instances: dict[int, App] = {0: app1, 1: app2}

        with patch("hassette.core.app_lifecycle_instances.mark_ready") as mock_mark_ready:
            await lifecycle_service.initialize_instances("test_app", instances, mock_manifest)

        app1.initialize.assert_awaited_once()
        app2.initialize.assert_awaited_once()
        mock_mark_ready.assert_called_once_with(app2, reason="initialized")

    async def test_emits_running_event_on_success(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_manifest: MagicMock,
        mock_hassette: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        """Emits HASSETTE_EVENT_APP_STATE_CHANGED with RUNNING status on success."""
        event_capture.install(mock_hassette)
        instances: dict[int, App] = {0: mock_app_instance}

        await lifecycle_service.initialize_instances("test_app", instances, mock_manifest)

        running_calls = app_state_payloads(event_capture, ResourceStatus.RUNNING)
        assert len(running_calls) == 1

    async def test_emits_failed_event_on_error(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_manifest: MagicMock,
        mock_hassette: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        """Emits HASSETTE_EVENT_APP_STATE_CHANGED with FAILED status on error."""
        event_capture.install(mock_hassette)
        mock_app_instance.initialize.side_effect = ValueError("boom")
        instances: dict[int, App] = {0: mock_app_instance}

        await lifecycle_service.initialize_instances("test_app", instances, mock_manifest)

        failed_calls = app_state_payloads(event_capture, ResourceStatus.FAILED)
        assert len(failed_calls) == 1


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
        await lifecycle_service.shutdown_instance(mock_app_instance, 0)

        mock_app_instance.shutdown.assert_awaited_once()

    async def test_catches_exceptions_and_flags_the_instance(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_hassette: MagicMock,
        mock_registry: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        """A raised shutdown doesn't raise here: it is FAILED with a failure entry and flagged, since the
        coordinator's COORDINATOR_FAILED report leaves its evidence incomplete.
        """
        event_capture.install(mock_hassette)
        error = RuntimeError("Shutdown failed")
        mock_app_instance.shutdown.side_effect = error
        mock_app_instance.teardown_report = TeardownReport(causes=(TeardownCause.COORDINATOR_FAILED,))

        await lifecycle_service.shutdown_instance(mock_app_instance, 0)

        failed_calls = app_state_payloads(event_capture, ResourceStatus.FAILED)
        assert len(failed_calls) == 1
        mock_registry.record_failure.assert_called_once_with("test_app", 0, error)
        mock_registry.flag_needs_restart.assert_called_once()

    async def test_unregisters_after_the_teardown_and_before_recording_the_outcome(
        self, lifecycle_service: AppLifecycleService, mock_app_instance: AsyncMock, mock_registry: MagicMock
    ) -> None:
        """Unregistering after the outcome would discard the failure entry the outcome just wrote."""
        order: list[str] = []

        async def teardown() -> TeardownReport:
            order.append("teardown")
            return TeardownReport(causes=(TeardownCause.SHUTDOWN_HOOK_TIMED_OUT,))

        mock_app_instance.shutdown = AsyncMock(side_effect=teardown)
        mock_registry.unregister_app.side_effect = lambda *_args: order.append("unregister")
        mock_registry.record_failure.side_effect = lambda *_args: order.append("record_failure")

        await lifecycle_service.shutdown_instance(mock_app_instance, 0)

        assert order == ["teardown", "unregister", "record_failure"]

    async def test_emits_stopped_event(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_hassette: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        """Emits HASSETTE_EVENT_APP_STATE_CHANGED with STOPPED status."""
        event_capture.install(mock_hassette)
        await lifecycle_service.shutdown_instance(mock_app_instance, 0)

        stopped_calls = app_state_payloads(event_capture, ResourceStatus.STOPPED)
        assert len(stopped_calls) == 1


class TestShutdownInstanceEntryDeadline:
    async def test_sets_the_entry_deadline_on_the_instance(
        self, lifecycle_service: AppLifecycleService, mock_app_instance: AsyncMock
    ) -> None:
        """The stop leg runs under one deadline the length of the stop stage, set before shutdown starts."""
        loop = asyncio.get_running_loop()
        before = loop.time()

        await lifecycle_service.shutdown_instance(mock_app_instance, 0)

        deadline = mock_app_instance._shutdown_deadline
        assert deadline is not None
        assert before < deadline <= loop.time() + lifecycle_service.entry_deadline_seconds

    async def test_a_caller_deadline_only_shortens_the_entry_deadline(
        self, lifecycle_service: AppLifecycleService, mock_app_instance: AsyncMock
    ) -> None:
        """Process exit passes what is left of its stop stage; the instance gets the closer of the two."""
        outer = deadline_in(1.0)

        await lifecycle_service.shutdown_instance(mock_app_instance, 0, deadline=outer)

        assert mock_app_instance._shutdown_deadline == outer

    async def test_walks_away_from_a_stop_that_outlives_its_deadline(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_hassette: MagicMock,
        mock_registry: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        """On expiry the instance is force-terminated, its listeners and jobs are removed by owner, it is
        recorded as force-terminated work, and it is reported FAILED with a registry failure entry.
        """
        event_capture.install(mock_hassette)
        mock_hassette.record_force_terminated = Mock()

        async def hang() -> TeardownReport:
            await asyncio.Event().wait()
            return TeardownReport()

        mock_app_instance.shutdown = AsyncMock(side_effect=hang)
        mock_app_instance._force_terminal = Mock()
        mock_app_instance.teardown_report = TeardownReport(causes=(TeardownCause.FORCED_TERMINAL,))

        report = await asyncio.wait_for(
            lifecycle_service.shutdown_instance(mock_app_instance, 3, deadline=deadline_in(0.1)), timeout=5
        )

        assert report is not None
        assert TeardownCause.FORCED_TERMINAL in report.causes
        mock_app_instance._force_terminal.assert_called_once()
        mock_app_instance.bus.remove_all_listeners.assert_called_once()
        mock_app_instance.scheduler.remove_all_jobs.assert_called_once()
        mock_hassette.record_force_terminated.assert_called_once_with([mock_app_instance.unique_name])
        mock_registry.record_failure.assert_called_once()
        app_key, index, exc = mock_registry.record_failure.call_args.args
        assert (app_key, index) == (mock_app_instance.app_key, 3)
        assert isinstance(exc, TimeoutError)
        mock_registry.flag_needs_restart.assert_called_once()
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
        mock_hassette.record_force_terminated = Mock()
        monkeypatch.setattr(app_lifecycle_instances, "WALK_AWAY_CLEANUP_TIMEOUT_SECONDS", 0.1)

        async def hang(*_args, **_kwargs) -> TeardownReport:
            await asyncio.Event().wait()
            return TeardownReport()

        mock_app_instance.shutdown = AsyncMock(side_effect=hang)
        mock_app_instance._force_terminal = Mock()
        mock_app_instance.scheduler.remove_all_jobs = AsyncMock(side_effect=hang)

        await asyncio.wait_for(
            lifecycle_service.shutdown_instance(mock_app_instance, 0, deadline=deadline_in(0.1)), timeout=5
        )

        mock_hassette.record_force_terminated.assert_called_once_with([mock_app_instance.unique_name])
        mock_registry.record_failure.assert_called_once()

    async def test_a_timed_out_hook_reports_failed_without_walking_away(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_hassette: MagicMock,
        mock_registry: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        """A stop that finished but whose hook was cut off at its bound is FAILED with a registry entry."""
        event_capture.install(mock_hassette)
        mock_app_instance.shutdown = AsyncMock(
            return_value=TeardownReport(causes=(TeardownCause.SHUTDOWN_HOOK_TIMED_OUT,))
        )
        mock_app_instance._force_terminal = Mock()

        await lifecycle_service.shutdown_instance(mock_app_instance, 0)

        mock_app_instance._force_terminal.assert_not_called()
        mock_registry.record_failure.assert_called_once()
        assert isinstance(mock_registry.record_failure.call_args.args[2], TimeoutError)
        mock_registry.flag_needs_restart.assert_not_called()
        assert len(app_state_payloads(event_capture, ResourceStatus.FAILED)) == 1

    async def test_a_stop_that_left_tasks_pending_is_failed_and_flagged_without_timing_out(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_hassette: MagicMock,
        mock_registry: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        """A stop that finished in time but left work running is FAILED and flagged, not STOPPED."""
        event_capture.install(mock_hassette)
        mock_app_instance.shutdown = AsyncMock(
            return_value=TeardownReport(causes=(TeardownCause.TASKS_PENDING,), pending_tasks=("app:poller",))
        )

        await lifecycle_service.shutdown_instance(mock_app_instance, 0)

        app_key, index, exc = mock_registry.record_failure.call_args.args
        assert (app_key, index) == ("test_app", 0)
        assert not isinstance(exc, TimeoutError)
        assert "app:poller" in str(exc)
        mock_registry.flag_needs_restart.assert_called_once()
        assert mock_registry.flag_needs_restart.call_args.kwargs["pending_tasks"] == ("app:poller",)
        assert app_state_payloads(event_capture, ResourceStatus.STOPPED) == []
        assert len(app_state_payloads(event_capture, ResourceStatus.FAILED)) == 1

    async def test_a_raised_hook_still_reports_stopped(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_hassette: MagicMock,
        mock_registry: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        """Only a timed-out stop is FAILED here; a hook that raised is evidence on the report, not a timeout."""
        event_capture.install(mock_hassette)
        mock_app_instance.shutdown = AsyncMock(
            return_value=TeardownReport(causes=(TeardownCause.SHUTDOWN_HOOK_FAILED,))
        )

        await lifecycle_service.shutdown_instance(mock_app_instance, 0)

        mock_registry.record_failure.assert_not_called()
        assert len(app_state_payloads(event_capture, ResourceStatus.STOPPED)) == 1


class TestShutdownInstances:
    async def test_empty_dict_returns_early(self, lifecycle_service: AppLifecycleService) -> None:
        """Returns early for empty instances dict."""
        await lifecycle_service.shutdown_instances({})

    async def test_stops_instances_concurrently(self, lifecycle_service: AppLifecycleService) -> None:
        """No instance's hooks wait on another's: two slow stops take about as long as one."""
        stop_seconds = 0.3

        async def slow_stop() -> TeardownReport:
            await asyncio.sleep(stop_seconds)
            return TeardownReport()

        instances = {}
        for idx in range(2):
            inst = make_mock_app_instance(instance_name=f"inst_{idx}")
            inst.shutdown = AsyncMock(side_effect=slow_stop)
            instances[idx] = inst

        loop = asyncio.get_running_loop()
        start = loop.time()
        await lifecycle_service.shutdown_instances(instances)
        elapsed = loop.time() - start

        assert elapsed < stop_seconds * 2, f"instances stopped one after another ({elapsed:.2f}s)"

    async def test_a_raising_stop_waits_for_its_siblings_before_raising(
        self, lifecycle_service: AppLifecycleService, mock_hassette: MagicMock
    ) -> None:
        """A stop that raises doesn't leave its sibling stops running detached."""
        finished: list[int] = []

        async def slow_stop() -> TeardownReport:
            await asyncio.sleep(0.1)
            finished.append(1)
            return TeardownReport()

        mocks = [make_mock_app_instance(instance_name=f"inst_{idx}") for idx in range(2)]
        mocks[1].shutdown = AsyncMock(side_effect=slow_stop)
        instances: dict[int, App] = dict(enumerate(mocks))
        mock_hassette.send_event = AsyncMock(side_effect=[RuntimeError("event bus down"), None, None, None])

        with pytest.raises(RuntimeError, match="event bus down"):
            await lifecycle_service.shutdown_instances(instances)

        assert finished == [1]

    async def test_calls_shutdown_for_each(self, lifecycle_service: AppLifecycleService) -> None:
        """Calls shutdown for each app instance."""
        app1 = make_mock_app_instance(instance_name="app1")
        app1.status = ResourceStatus.RUNNING
        app2 = make_mock_app_instance(instance_name="app2")
        app2.status = ResourceStatus.RUNNING

        instances: dict[int, App] = {0: app1, 1: app2}

        await lifecycle_service.shutdown_instances(instances)

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
        instances: dict[int, App] = {0: mock_app_instance}

        await lifecycle_service.shutdown_instances(instances)

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

        set_registry_apps(mock_registry, {"app1": {0: app1}, "app2": {0: app2}})

        await lifecycle_service.shutdown_all()

        app1.shutdown.assert_awaited_once()
        app2.shutdown.assert_awaited_once()

    async def test_stops_apps_when_the_loops_fallback_bucket_is_sealed(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """App stops still run at exit, when the root's sealed TaskBucket is the loop's task-factory fallback."""
        app1 = make_mock_app_instance(instance_name="app1")
        app2 = make_mock_app_instance(instance_name="app2")
        set_registry_apps(mock_registry, {"app1": {0: app1}, "app2": {0: app2}})

        with sealed_fallback_task_factory():
            await lifecycle_service.shutdown_all()

        app1.shutdown.assert_awaited_once()
        app2.shutdown.assert_awaited_once()

    async def test_clears_registry(self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock) -> None:
        """Calls registry.clear_all() after shutdown."""
        set_registry_apps(mock_registry, {})

        await lifecycle_service.shutdown_all()

        mock_registry.clear_all.assert_called_once()
