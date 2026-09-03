"""Unit tests for AppLifecycleService instance-level lifecycle operations.

Complements test_app_lifecycle_service.py (init/properties/bootstrap-admission/apply-changes
gating), test_app_lifecycle_service_coverage.py (remaining branch coverage), and the
operation-family files: test_app_lifecycle_service_start_stop.py (whole-app start/stop),
test_app_lifecycle_service_per_instance_ops.py (per-instance start/stop/reload and locking),
test_app_lifecycle_service_reload.py (change application and reload), and
test_app_lifecycle_service_reconcile.py (resolve_only_apps/refresh_config/reconcile). This
file covers instance initialization, failed-instance cleanup, and instance/all-app shutdown.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, call, patch

from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.scheduler.classes import Job
from hassette.scheduler.scheduler import Scheduler
from hassette.testing import EventCapture
from hassette.types import Topic
from hassette.types.enums import ResourceStatus
from tests.support.factories import make_mock_parent
from tests.support.helpers import noop
from tests.support.mock_hassette import make_mock_hassette

from .conftest import make_mock_app_instance, set_registry_apps


class TestInitializeInstances:
    async def test_success_calls_initialize_and_mark_ready(
        self, lifecycle_service: AppLifecycleService, mock_app_instance: AsyncMock, mock_manifest: MagicMock
    ) -> None:
        """Calls initialize() and mark_ready() on each instance."""
        instances = {0: mock_app_instance}

        with patch("hassette.core.app_lifecycle_service.mark_ready") as mock_mark_ready:
            await lifecycle_service.initialize_instances("test_app", instances, mock_manifest)

        mock_app_instance.initialize.assert_awaited_once()
        mock_mark_ready.assert_called_once_with(mock_app_instance, reason="initialized")

    async def test_multiple_instances(self, lifecycle_service: AppLifecycleService, mock_manifest: MagicMock) -> None:
        """Initializes all provided instances."""
        app1 = make_mock_app_instance(instance_name="instance_0", class_name="TestApp")
        app2 = make_mock_app_instance(instance_name="instance_1", class_name="TestApp")
        instances = {0: app1, 1: app2}

        with patch("hassette.core.app_lifecycle_service.mark_ready") as mock_mark_ready:
            await lifecycle_service.initialize_instances("test_app", instances, mock_manifest)

        app1.initialize.assert_awaited_once()
        app2.initialize.assert_awaited_once()
        assert mock_mark_ready.call_args_list == [
            call(app1, reason="initialized"),
            call(app2, reason="initialized"),
        ]

    async def test_timeout_records_failure(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_manifest: MagicMock,
        mock_registry: MagicMock,
    ) -> None:
        """Sets status to STOPPED and records failure on TimeoutError."""
        mock_app_instance.initialize.side_effect = TimeoutError("Timed out")
        instances = {0: mock_app_instance}

        await lifecycle_service.initialize_instances("test_app", instances, mock_manifest)

        assert mock_app_instance.status == ResourceStatus.STOPPED
        mock_registry.record_failure.assert_called_once()
        call_args = mock_registry.record_failure.call_args
        assert call_args[0][0] == "test_app"
        assert call_args[0][1] == 0
        assert isinstance(call_args[0][2], TimeoutError)

    async def test_exception_records_failure(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_manifest: MagicMock,
        mock_registry: MagicMock,
    ) -> None:
        """Sets status to STOPPED and records failure on any exception."""
        error = ValueError("Init failed")
        mock_app_instance.initialize.side_effect = error
        instances = {0: mock_app_instance}

        await lifecycle_service.initialize_instances("test_app", instances, mock_manifest)

        assert mock_app_instance.status == ResourceStatus.STOPPED
        mock_registry.record_failure.assert_called_once_with("test_app", 0, error)

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
        instances = {0: mock_app_instance}

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

        instances = {0: app1, 1: app2}

        with patch("hassette.core.app_lifecycle_service.mark_ready") as mock_mark_ready:
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
        instances = {0: mock_app_instance}

        await lifecycle_service.initialize_instances("test_app", instances, mock_manifest)

        running_calls = [
            payload
            for payload in event_capture.payloads(Topic.HASSETTE_EVENT_APP_STATE_CHANGED)
            if payload.status == ResourceStatus.RUNNING
        ]
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
        instances = {0: mock_app_instance}

        await lifecycle_service.initialize_instances("test_app", instances, mock_manifest)

        failed_calls = [
            payload
            for payload in event_capture.payloads(Topic.HASSETTE_EVENT_APP_STATE_CHANGED)
            if payload.status == ResourceStatus.FAILED
        ]
        assert len(failed_calls) == 1


class TestCleanupFailedInstance:
    async def test_exception_cleans_up_listeners_before_record_failure(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_manifest: MagicMock,
    ) -> None:
        """Bus listeners registered before the failure are removed via Bus.remove_all_listeners."""
        mock_app_instance.initialize.side_effect = ValueError("boom")
        instances = {0: mock_app_instance}

        await lifecycle_service.initialize_instances("test_app", instances, mock_manifest)

        mock_app_instance.bus.remove_all_listeners.assert_called_once()

    async def test_exception_cleans_up_jobs_before_record_failure(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_manifest: MagicMock,
        mock_hassette: MagicMock,
    ) -> None:
        """Scheduler jobs registered before the failure are removed via the same
        registry-aware path as normal shutdown (Scheduler.remove_all_jobs), not a
        heap-only scan by owner string (see the manual-job regression test below, which
        covers a job that never touches the heap).
        """
        mock_app_instance.initialize.side_effect = ValueError("boom")
        instances = {0: mock_app_instance}

        await lifecycle_service.initialize_instances("test_app", instances, mock_manifest)

        mock_app_instance.scheduler.remove_all_jobs.assert_called_once()

    async def test_timeout_cleans_up_listeners_and_jobs(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_manifest: MagicMock,
        mock_hassette: MagicMock,
    ) -> None:
        """TimeoutError path also cleans up listeners and jobs."""
        mock_app_instance.initialize.side_effect = TimeoutError("Timed out")
        instances = {0: mock_app_instance}

        await lifecycle_service.initialize_instances("test_app", instances, mock_manifest)

        mock_app_instance.bus.remove_all_listeners.assert_called_once()
        mock_app_instance.scheduler.remove_all_jobs.assert_called_once()

    async def test_cleanup_runs_before_record_failure(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_manifest: MagicMock,
        mock_hassette: MagicMock,
        mock_registry: MagicMock,
    ) -> None:
        """Cleanup runs before record_failure pops the instance from the registry."""
        call_order: list[str] = []

        mock_app_instance.bus.remove_all_listeners = Mock(side_effect=lambda: call_order.append("cleanup_listeners"))

        async def track_jobs() -> None:
            call_order.append("cleanup_jobs")
            return await asyncio.sleep(0)

        mock_app_instance.scheduler.remove_all_jobs = Mock(side_effect=track_jobs)
        mock_registry.record_failure.side_effect = lambda *_args: call_order.append("record_failure")
        mock_app_instance.initialize.side_effect = ValueError("boom")
        instances = {0: mock_app_instance}

        await lifecycle_service.initialize_instances("test_app", instances, mock_manifest)

        assert call_order == ["cleanup_listeners", "cleanup_jobs", "record_failure"]

    async def test_cleanup_failure_does_not_prevent_record_failure(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_manifest: MagicMock,
        mock_registry: MagicMock,
    ) -> None:
        """If cleanup raises, init failure is still recorded."""
        mock_app_instance.bus.remove_all_listeners.side_effect = RuntimeError("cleanup exploded")
        mock_app_instance.initialize.side_effect = ValueError("boom")
        instances = {0: mock_app_instance}

        await lifecycle_service.initialize_instances("test_app", instances, mock_manifest)

        mock_registry.record_failure.assert_called_once()

    async def test_bus_cleanup_failure_does_not_skip_scheduler_cleanup(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_manifest: MagicMock,
        mock_hassette: MagicMock,
    ) -> None:
        """Bus listener cleanup failure does not prevent scheduler job cleanup."""
        mock_app_instance.bus.remove_all_listeners.side_effect = RuntimeError("bus exploded")
        mock_app_instance.initialize.side_effect = ValueError("boom")
        instances = {0: mock_app_instance}

        await lifecycle_service.initialize_instances("test_app", instances, mock_manifest)

        mock_app_instance.scheduler.remove_all_jobs.assert_called_once()

    async def test_manual_job_reaches_removal_not_just_heap_resident_jobs(self) -> None:
        """A manual job (never on the scheduler heap) owned by a failed-init instance
        must still be removed by cleanup_failed_instance().

        Uses a real Scheduler (not a mock) so the manual job actually lives only in
        the scheduler's own registry, never on the heap — exactly the case a heap-only
        scan by owner string could not reach.
        Asserting SchedulerService.remove_jobs() was awaited with the manual job proves
        cleanup now goes through the same identity-checked, registry-aware path as
        normal shutdown (Scheduler.remove_all_jobs), not the heap-only owner scan.

        Also asserts the removal callback registered by Scheduler.__init__ is
        deregistered afterward — cleanup_failed_instance() discards this Scheduler for
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
        inst.app_config.instance_name = "failed_instance"
        inst.bus.remove_all_listeners = Mock()
        inst.scheduler = scheduler
        inst.cache.close = AsyncMock()

        await lifecycle_service.cleanup_failed_instance(inst)

        hassette.scheduler_service.remove_jobs.assert_awaited_once_with([job])
        hassette.scheduler_service.deregister_removal_callback.assert_called_once_with(scheduler.owner_id)


class TestShutdownInstance:
    async def test_calls_shutdown(self, lifecycle_service: AppLifecycleService, mock_app_instance: AsyncMock) -> None:
        """Calls inst.shutdown()."""
        await lifecycle_service.shutdown_instance(mock_app_instance)

        mock_app_instance.shutdown.assert_awaited_once()

    async def test_catches_exceptions(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_hassette: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        """Doesn't raise on shutdown failure; emits FAILED state event."""
        event_capture.install(mock_hassette)
        mock_app_instance.shutdown.side_effect = RuntimeError("Shutdown failed")

        await lifecycle_service.shutdown_instance(mock_app_instance)

        failed_calls = [
            payload
            for payload in event_capture.payloads(Topic.HASSETTE_EVENT_APP_STATE_CHANGED)
            if payload.status == ResourceStatus.FAILED
        ]
        assert len(failed_calls) == 1

    async def test_emits_stopped_event(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_hassette: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        """Emits HASSETTE_EVENT_APP_STATE_CHANGED with STOPPED status."""
        event_capture.install(mock_hassette)
        await lifecycle_service.shutdown_instance(mock_app_instance)

        stopped_calls = [
            payload
            for payload in event_capture.payloads(Topic.HASSETTE_EVENT_APP_STATE_CHANGED)
            if payload.status == ResourceStatus.STOPPED
        ]
        assert len(stopped_calls) == 1


class TestShutdownInstances:
    async def test_empty_dict_returns_early(self, lifecycle_service: AppLifecycleService) -> None:
        """Returns early for empty instances dict."""
        await lifecycle_service.shutdown_instances({})

    async def test_calls_shutdown_for_each(self, lifecycle_service: AppLifecycleService) -> None:
        """Calls shutdown for each app instance."""
        app1 = AsyncMock()
        app1.status = ResourceStatus.RUNNING
        app2 = AsyncMock()
        app2.status = ResourceStatus.RUNNING

        instances = {0: app1, 1: app2}

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
        instances = {0: mock_app_instance}

        await lifecycle_service.shutdown_instances(instances)

        first_event = event_capture.events[0]
        assert first_event.topic == Topic.HASSETTE_EVENT_APP_STATE_CHANGED
        assert first_event.payload.data.status == ResourceStatus.STOPPING


class TestShutdownAll:
    async def test_shuts_down_all_registered_apps(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """Calls shutdown for each app in registry."""
        app1 = AsyncMock()
        app1.status = ResourceStatus.RUNNING
        app2 = AsyncMock()
        app2.status = ResourceStatus.RUNNING

        set_registry_apps(mock_registry, {"app1": {0: app1}, "app2": {0: app2}})

        await lifecycle_service.shutdown_all()

        app1.shutdown.assert_awaited_once()
        app2.shutdown.assert_awaited_once()

    async def test_clears_registry(self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock) -> None:
        """Calls registry.clear_all() after shutdown."""
        set_registry_apps(mock_registry, {})

        await lifecycle_service.shutdown_all()

        mock_registry.clear_all.assert_called_once()
