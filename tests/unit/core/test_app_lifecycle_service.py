"""Unit tests for AppLifecycleService."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, call, patch

import pytest

from hassette.bus import Bus
from hassette.core.app_change_detector import ChangeSet
from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.scheduler.scheduler import Scheduler
from hassette.test_utils import EventCapture, make_mock_hassette
from hassette.test_utils.factories import make_mock_parent
from hassette.test_utils.helpers import noop
from hassette.types import Topic
from hassette.types.enums import ResourceStatus

from .conftest import make_mock_app_instance, set_registry_apps


class TestAppLifecycleServiceInit:
    def test_stores_registry_reference(
        self, mock_hassette: MagicMock, mock_registry: MagicMock, mock_factory: MagicMock
    ) -> None:
        """Verify constructor stores the registry reference."""
        with (
            patch("hassette.core.app_lifecycle_service.AppFactory", return_value=mock_factory),
            patch("hassette.core.app_lifecycle_service.AppChangeDetector"),
        ):
            service = AppLifecycleService(mock_hassette, parent=None, registry=mock_registry)
        assert service.registry is mock_registry

    def test_creates_factory_internally(self, mock_hassette: MagicMock, mock_registry: MagicMock) -> None:
        """Verify constructor creates an AppFactory."""
        with (
            patch("hassette.core.app_lifecycle_service.AppFactory") as factory_cls,
            patch("hassette.core.app_lifecycle_service.AppChangeDetector"),
        ):
            service = AppLifecycleService(mock_hassette, parent=None, registry=mock_registry)
            factory_cls.assert_called_once_with(mock_hassette, mock_registry)
            assert service.factory is factory_cls.return_value

    def test_creates_change_detector_internally(
        self, mock_hassette: MagicMock, mock_registry: MagicMock, mock_factory: MagicMock
    ) -> None:
        """Verify constructor creates an AppChangeDetector."""
        with (
            patch("hassette.core.app_lifecycle_service.AppFactory", return_value=mock_factory),
            patch("hassette.core.app_lifecycle_service.AppChangeDetector") as detector_cls,
        ):
            service = AppLifecycleService(mock_hassette, parent=None, registry=mock_registry)
            detector_cls.assert_called_once()
            assert service.change_detector is detector_cls.return_value

    def test_does_not_create_bus_child(
        self, mock_hassette: MagicMock, mock_registry: MagicMock, mock_factory: MagicMock
    ) -> None:
        """Verify constructor does not create a Bus child (file-watcher subscription belongs to AppHandler.bus)."""
        with (
            patch("hassette.core.app_lifecycle_service.AppFactory", return_value=mock_factory),
            patch("hassette.core.app_lifecycle_service.AppChangeDetector"),
        ):
            service = AppLifecycleService(mock_hassette, parent=None, registry=mock_registry)

        assert not any(isinstance(child, Bus) for child in service.children)


class TestOnlyAppRegistryAgreement:
    """Pin: registry.only_apps must equal the value passed to detect_changes."""

    async def test_detect_changes_receives_registry_only_apps(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """The value passed as only_apps to detect_changes matches registry.only_apps at call time."""
        mock_registry.only_apps = frozenset({"pinned_app"})

        captured_only_apps: list[frozenset[str] | None] = []

        def capture_only_apps(_original, _current, _changed_paths, *, only_apps=None):
            captured_only_apps.append(only_apps)
            return ChangeSet(
                orphans=frozenset(),
                new_apps=frozenset(),
                reimport_apps=frozenset(),
                reload_apps=frozenset(),
            )

        lifecycle_service.change_detector.detect_changes = capture_only_apps  # pyright: ignore[reportAttributeAccessIssue]

        await lifecycle_service.handle_change_event()

        assert len(captured_only_apps) == 1
        assert captured_only_apps[0] == mock_registry.only_apps


class TestAppLifecycleServiceProperties:
    def test_startup_timeout_from_config(
        self, lifecycle_service: AppLifecycleService, mock_hassette: MagicMock
    ) -> None:
        """Returns hassette.config.lifecycle.app_startup_timeout_seconds."""
        assert lifecycle_service.startup_timeout == mock_hassette.config.lifecycle.app_startup_timeout_seconds

    def test_shutdown_timeout_from_config(
        self, lifecycle_service: AppLifecycleService, mock_hassette: MagicMock
    ) -> None:
        """Returns hassette.config.lifecycle.app_shutdown_timeout_seconds."""
        assert lifecycle_service.shutdown_timeout == mock_hassette.config.lifecycle.app_shutdown_timeout_seconds


class TestInitializeInstances:
    async def test_success_calls_initialize_and_mark_ready(
        self, lifecycle_service: AppLifecycleService, mock_app_instance: AsyncMock, mock_manifest: MagicMock
    ) -> None:
        """Calls initialize() and mark_ready() on each instance."""
        instances = {0: mock_app_instance}

        with patch("hassette.core.app_lifecycle_service.mark_ready") as mock_mark_ready:
            await lifecycle_service.initialize_instances("test_app", instances, mock_manifest)

        mock_app_instance.initialize.assert_called_once()
        mock_mark_ready.assert_called_once_with(mock_app_instance, reason="initialized")

    async def test_multiple_instances(self, lifecycle_service: AppLifecycleService, mock_manifest: MagicMock) -> None:
        """Initializes all provided instances."""
        app1 = make_mock_app_instance(instance_name="instance_0", class_name="TestApp")
        app2 = make_mock_app_instance(instance_name="instance_1", class_name="TestApp")
        instances = {0: app1, 1: app2}

        with patch("hassette.core.app_lifecycle_service.mark_ready") as mock_mark_ready:
            await lifecycle_service.initialize_instances("test_app", instances, mock_manifest)

        app1.initialize.assert_called_once()
        app2.initialize.assert_called_once()
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

        app1.initialize.assert_called_once()
        app2.initialize.assert_called_once()
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
        registry-aware path as normal shutdown (Scheduler.remove_all_jobs), not the
        heap-only SchedulerService.remove_jobs_by_owner (see the manual-job regression
        test below, which covers a job that never touches the heap).
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

        async def track_jobs():
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
        the scheduler's own registry, never on the heap — exactly the case the old
        SchedulerService.remove_jobs_by_owner() (a heap-only scan) could not reach.
        Asserting SchedulerService.remove_jobs() was awaited with the manual job proves
        cleanup now goes through the same identity-checked, registry-aware path as
        normal shutdown (Scheduler.remove_all_jobs), not the heap-only owner scan.

        Also asserts the removal callback registered by Scheduler.__init__ is
        deregistered afterward — cleanup_failed_instance() discards this Scheduler for
        good (unlike test_utils.reset.reset_scheduler, which reuses its instance), so it
        must explicitly deregister rather than leak the stale callback.
        """
        hassette = make_mock_hassette(sealed=False)

        async def _add_job(job):
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

        mock_app_instance.shutdown.assert_called_once()

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

        app1.shutdown.assert_called_once()
        app2.shutdown.assert_called_once()

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

        app1.shutdown.assert_called_once()
        app2.shutdown.assert_called_once()

    async def test_clears_registry(self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock) -> None:
        """Calls registry.clear_all() after shutdown."""
        set_registry_apps(mock_registry, {})

        await lifecycle_service.shutdown_all()

        mock_registry.clear_all.assert_called_once()


class TestBootstrapApps:
    async def test_skips_when_no_manifests(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock, mock_hassette: MagicMock
    ) -> None:
        """Returns early when no manifests are configured."""
        mock_registry.manifests = {}

        await lifecycle_service.bootstrap_apps()

        mock_hassette.send_event.assert_not_called()

    async def test_emits_load_completed_event(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_hassette: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        """Emits APP_LOAD_COMPLETED after starting apps."""
        event_capture.install(mock_hassette)
        mock_registry.manifests = {"app_a": MagicMock()}
        mock_registry.active_manifests = {}
        mock_registry.get_snapshot = Mock(return_value=MagicMock(running_count=0, failed_count=0))

        await lifecycle_service.bootstrap_apps()

        completed_calls = event_capture.by_topic(Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED)
        assert len(completed_calls) == 1

    async def test_handles_crash(self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock) -> None:
        """Calls handle_crash and re-raises on exception."""
        mock_registry.manifests = {"app_a": MagicMock()}
        lifecycle_service.resolve_only_apps = AsyncMock(side_effect=RuntimeError("crash"))

        with patch("hassette.core.app_lifecycle_service.handle_crash") as mock_handle_crash:
            with pytest.raises(RuntimeError, match="crash"):
                await lifecycle_service.bootstrap_apps()

            mock_handle_crash.assert_called_once()
            assert mock_handle_crash.call_args[0][0] is lifecycle_service
            assert isinstance(mock_handle_crash.call_args[0][1], RuntimeError)


class TestStartApps:
    async def test_gathers_all_app_starts(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """Starts only autostart_manifests apps (not all active_manifests) by default."""
        manifest_a = MagicMock()
        manifest_b = MagicMock()
        mock_registry.autostart_manifests = {"app_a": manifest_a, "app_b": manifest_b}
        mock_registry.get_manifest = Mock(side_effect=lambda k: {"app_a": manifest_a, "app_b": manifest_b}.get(k))
        mock_registry.get_apps_by_key = Mock(return_value={})

        await lifecycle_service.start_apps()

        assert mock_factory.create_instances.call_count == 2

    async def test_excludes_autostart_false_apps_by_default(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """Apps not in autostart_manifests are not started when no explicit set is passed."""
        manifest_a = MagicMock()
        # autostart_manifests only contains app_a; active_manifests also has app_b (autostart=false)
        mock_registry.autostart_manifests = {"app_a": manifest_a}
        mock_registry.get_manifest = Mock(side_effect=lambda k: {"app_a": manifest_a}.get(k))
        mock_registry.get_apps_by_key = Mock(return_value={})

        await lifecycle_service.start_apps()

        assert mock_factory.create_instances.call_count == 1


class TestShouldAutostart:
    @pytest.mark.parametrize(
        ("autostart", "manifest_exists", "expected"),
        [
            (True, True, True),
            (False, True, False),
            (None, False, False),
        ],
        ids=["autostart_true", "autostart_false", "manifest_missing"],
    )
    def test_should_autostart(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        autostart: bool | None,
        manifest_exists: bool,
        expected: bool,
    ) -> None:
        if manifest_exists:
            manifest = MagicMock()
            manifest.autostart = autostart
            mock_registry.get_manifest = Mock(return_value=manifest)
        else:
            mock_registry.get_manifest = Mock(return_value=None)

        assert lifecycle_service.should_autostart("app_a") is expected


class TestShouldAutoReconcile:
    @pytest.mark.parametrize(
        ("autostart", "is_running", "expected"),
        [
            (False, True, True),
            (True, False, True),
            (False, False, False),
        ],
        ids=["running_overrides_autostart", "autostart_true", "not_running_no_autostart"],
    )
    def test_should_auto_reconcile(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        autostart: bool,
        is_running: bool,
        expected: bool,
    ) -> None:
        manifest = MagicMock()
        manifest.autostart = autostart
        mock_registry.get_manifest = Mock(return_value=manifest)
        set_registry_apps(mock_registry, {"app_a": {0: MagicMock()}} if is_running else {})

        assert lifecycle_service.should_auto_reconcile("app_a") is expected


class TestApplyChangesGating:
    async def test_new_apps_autostart_false_not_started(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """new_apps with autostart=False are skipped in apply_changes."""
        manifest = MagicMock()
        manifest.autostart = False
        mock_registry.get_manifest = Mock(return_value=manifest)
        set_registry_apps(mock_registry, {})
        lifecycle_service.start_app = AsyncMock()

        changes = ChangeSet(
            orphans=frozenset(),
            new_apps=frozenset({"app_a"}),
            reimport_apps=frozenset(),
            reload_apps=frozenset(),
        )
        await lifecycle_service.apply_changes(changes)

        lifecycle_service.start_app.assert_not_called()

    async def test_new_apps_autostart_true_are_started(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """new_apps with autostart=True are started in apply_changes."""
        manifest = MagicMock()
        manifest.autostart = True
        mock_registry.get_manifest = Mock(return_value=manifest)
        set_registry_apps(mock_registry, {})
        lifecycle_service.start_app = AsyncMock()

        changes = ChangeSet(
            orphans=frozenset(),
            new_apps=frozenset({"app_a"}),
            reimport_apps=frozenset(),
            reload_apps=frozenset(),
        )
        await lifecycle_service.apply_changes(changes)

        lifecycle_service.start_app.assert_called_once_with("app_a")

    async def test_reload_apps_running_autostart_false_are_reloaded(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """reload_apps for a running app are always reconciled (autostart=False, but running)."""
        manifest = MagicMock()
        manifest.autostart = False
        mock_registry.get_manifest = Mock(return_value=manifest)
        set_registry_apps(mock_registry, {"app_a": {0: MagicMock()}})
        lifecycle_service.reload_app = AsyncMock()

        changes = ChangeSet(
            orphans=frozenset(),
            new_apps=frozenset(),
            reimport_apps=frozenset(),
            reload_apps=frozenset({"app_a"}),
        )
        await lifecycle_service.apply_changes(changes)

        lifecycle_service.reload_app.assert_called_once_with("app_a")

    async def test_reload_apps_not_running_autostart_false_are_skipped(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """reload_apps for a non-running autostart=False app are skipped."""
        manifest = MagicMock()
        manifest.autostart = False
        mock_registry.get_manifest = Mock(return_value=manifest)
        set_registry_apps(mock_registry, {})
        lifecycle_service.reload_app = AsyncMock()

        changes = ChangeSet(
            orphans=frozenset(),
            new_apps=frozenset(),
            reimport_apps=frozenset(),
            reload_apps=frozenset({"app_a"}),
        )
        await lifecycle_service.apply_changes(changes)

        lifecycle_service.reload_app.assert_not_called()

    async def test_reimport_apps_running_autostart_false_are_reloaded(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """reimport_apps for a running autostart=False app are reconciled with force_reload."""
        manifest = MagicMock()
        manifest.autostart = False
        mock_registry.get_manifest = Mock(return_value=manifest)
        set_registry_apps(mock_registry, {"app_a": {0: MagicMock()}})
        lifecycle_service.reload_app = AsyncMock()

        changes = ChangeSet(
            orphans=frozenset(),
            new_apps=frozenset(),
            reimport_apps=frozenset({"app_a"}),
            reload_apps=frozenset(),
        )
        await lifecycle_service.apply_changes(changes)

        lifecycle_service.reload_app.assert_called_once_with("app_a", force_reload=True)

    async def test_reimport_apps_not_running_autostart_false_are_skipped(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """reimport_apps for a non-running autostart=False app are skipped."""
        manifest = MagicMock()
        manifest.autostart = False
        mock_registry.get_manifest = Mock(return_value=manifest)
        set_registry_apps(mock_registry, {})
        lifecycle_service.reload_app = AsyncMock()

        changes = ChangeSet(
            orphans=frozenset(),
            new_apps=frozenset(),
            reimport_apps=frozenset({"app_a"}),
            reload_apps=frozenset(),
        )
        await lifecycle_service.apply_changes(changes)

        lifecycle_service.reload_app.assert_not_called()

    async def test_orphans_stopped_unconditionally(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """Orphaned apps are stopped regardless of autostart."""
        manifest = MagicMock()
        manifest.autostart = False
        mock_registry.get_manifest = Mock(return_value=manifest)
        set_registry_apps(mock_registry, {})
        lifecycle_service.stop_app = AsyncMock()

        changes = ChangeSet(
            orphans=frozenset({"app_a"}),
            new_apps=frozenset(),
            reimport_apps=frozenset(),
            reload_apps=frozenset(),
        )
        await lifecycle_service.apply_changes(changes)

        lifecycle_service.stop_app.assert_called_once_with("app_a")
