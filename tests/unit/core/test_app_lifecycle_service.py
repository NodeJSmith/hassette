"""Unit tests for AppLifecycleService."""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from hassette.bus import Bus
from hassette.core.app_change_detector import ChangeSet
from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.types import Topic
from hassette.types.enums import ResourceStatus

from .conftest import make_mock_app_instance


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
    """Pin: registry.only_app must equal the value passed to detect_changes."""

    async def test_detect_changes_receives_registry_only_app(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """The value passed as only_app to detect_changes matches registry.only_app at call time."""
        mock_registry.only_app = "pinned_app"

        captured_only_app: list[str | None] = []

        def capture_only_app(_original, _current, _changed_paths, *, only_app=None):
            captured_only_app.append(only_app)
            return ChangeSet(
                orphans=frozenset(),
                new_apps=frozenset(),
                reimport_apps=frozenset(),
                reload_apps=frozenset(),
            )

        lifecycle_service.change_detector.detect_changes = capture_only_app  # pyright: ignore[reportAttributeAccessIssue]

        await lifecycle_service.handle_change_event()

        assert len(captured_only_app) == 1
        assert captured_only_app[0] == mock_registry.only_app


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

        await lifecycle_service.initialize_instances("test_app", instances, mock_manifest)

        mock_app_instance.initialize.assert_called_once()
        mock_app_instance.mark_ready.assert_called_once_with(reason="initialized")

    async def test_multiple_instances(self, lifecycle_service: AppLifecycleService, mock_manifest: MagicMock) -> None:
        """Initializes all provided instances."""
        app1 = make_mock_app_instance(instance_name="instance_0", class_name="TestApp")
        app2 = make_mock_app_instance(instance_name="instance_1", class_name="TestApp")
        instances = {0: app1, 1: app2}

        await lifecycle_service.initialize_instances("test_app", instances, mock_manifest)

        app1.initialize.assert_called_once()
        app1.mark_ready.assert_called_once()
        app2.initialize.assert_called_once()
        app2.mark_ready.assert_called_once()

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

        await lifecycle_service.initialize_instances("test_app", instances, mock_manifest)

        app1.initialize.assert_called_once()
        app2.initialize.assert_called_once()
        app2.mark_ready.assert_called_once()

    async def test_emits_running_event_on_success(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_manifest: MagicMock,
        mock_hassette: MagicMock,
    ) -> None:
        """Emits HASSETTE_EVENT_APP_STATE_CHANGED with RUNNING status on success."""
        instances = {0: mock_app_instance}

        await lifecycle_service.initialize_instances("test_app", instances, mock_manifest)

        calls = mock_hassette.send_event.call_args_list
        running_calls = [
            call
            for call in calls
            if call[0][0].topic == Topic.HASSETTE_EVENT_APP_STATE_CHANGED
            and call[0][0].payload.data.status == ResourceStatus.RUNNING
        ]
        assert len(running_calls) == 1

    async def test_emits_failed_event_on_error(
        self,
        lifecycle_service: AppLifecycleService,
        mock_app_instance: AsyncMock,
        mock_manifest: MagicMock,
        mock_hassette: MagicMock,
    ) -> None:
        """Emits HASSETTE_EVENT_APP_STATE_CHANGED with FAILED status on error."""
        mock_app_instance.initialize.side_effect = ValueError("boom")
        instances = {0: mock_app_instance}

        await lifecycle_service.initialize_instances("test_app", instances, mock_manifest)

        calls = mock_hassette.send_event.call_args_list
        failed_calls = [
            call
            for call in calls
            if call[0][0].topic == Topic.HASSETTE_EVENT_APP_STATE_CHANGED
            and call[0][0].payload.data.status == ResourceStatus.FAILED
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
        """Scheduler jobs registered before the failure are removed."""
        mock_app_instance.initialize.side_effect = ValueError("boom")
        instances = {0: mock_app_instance}

        await lifecycle_service.initialize_instances("test_app", instances, mock_manifest)

        mock_hassette.scheduler_service.remove_jobs_by_owner.assert_called_once_with(
            mock_app_instance.scheduler.owner_id,
        )

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
        mock_hassette.scheduler_service.remove_jobs_by_owner.assert_called_once_with(
            mock_app_instance.scheduler.owner_id,
        )

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
        original_side_effect = mock_hassette.scheduler_service.remove_jobs_by_owner.side_effect

        async def track_jobs(owner):
            call_order.append("cleanup_jobs")
            return await original_side_effect(owner)

        mock_hassette.scheduler_service.remove_jobs_by_owner = MagicMock(side_effect=track_jobs)
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

        mock_hassette.scheduler_service.remove_jobs_by_owner.assert_called_once_with(
            mock_app_instance.scheduler.owner_id,
        )


class TestShutdownInstance:
    async def test_calls_shutdown(self, lifecycle_service: AppLifecycleService, mock_app_instance: AsyncMock) -> None:
        """Calls inst.shutdown()."""
        await lifecycle_service.shutdown_instance(mock_app_instance)

        mock_app_instance.shutdown.assert_called_once()

    async def test_catches_exceptions(
        self, lifecycle_service: AppLifecycleService, mock_app_instance: AsyncMock, mock_hassette: MagicMock
    ) -> None:
        """Doesn't raise on shutdown failure; emits FAILED state event."""
        mock_app_instance.shutdown.side_effect = RuntimeError("Shutdown failed")

        await lifecycle_service.shutdown_instance(mock_app_instance)

        calls = mock_hassette.send_event.call_args_list
        failed_calls = [
            call
            for call in calls
            if call[0][0].topic == Topic.HASSETTE_EVENT_APP_STATE_CHANGED
            and call[0][0].payload.data.status == ResourceStatus.FAILED
        ]
        assert len(failed_calls) == 1

    async def test_emits_stopped_event(
        self, lifecycle_service: AppLifecycleService, mock_app_instance: AsyncMock, mock_hassette: MagicMock
    ) -> None:
        """Emits HASSETTE_EVENT_APP_STATE_CHANGED with STOPPED status."""
        await lifecycle_service.shutdown_instance(mock_app_instance)

        calls = mock_hassette.send_event.call_args_list
        stopped_calls = [
            call
            for call in calls
            if call[0][0].topic == Topic.HASSETTE_EVENT_APP_STATE_CHANGED
            and call[0][0].payload.data.status == ResourceStatus.STOPPED
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
        self, lifecycle_service: AppLifecycleService, mock_app_instance: AsyncMock, mock_hassette: MagicMock
    ) -> None:
        """Emits STOPPING event for each instance before shutting down."""
        mock_app_instance.status = ResourceStatus.RUNNING
        instances = {0: mock_app_instance}

        await lifecycle_service.shutdown_instances(instances)

        first_call = mock_hassette.send_event.call_args_list[0]
        assert first_call[0][0].topic == Topic.HASSETTE_EVENT_APP_STATE_CHANGED
        assert first_call[0][0].payload.data.status == ResourceStatus.STOPPING


class TestShutdownAll:
    async def test_shuts_down_all_registered_apps(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """Calls shutdown for each app in registry."""
        app1 = AsyncMock()
        app1.status = ResourceStatus.RUNNING
        app2 = AsyncMock()
        app2.status = ResourceStatus.RUNNING

        mock_registry.apps = {"app1": {0: app1}, "app2": {0: app2}}

        await lifecycle_service.shutdown_all()

        app1.shutdown.assert_called_once()
        app2.shutdown.assert_called_once()

    async def test_clears_registry(self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock) -> None:
        """Calls registry.clear_all() after shutdown."""
        mock_registry.apps = {}

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
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock, mock_hassette: MagicMock
    ) -> None:
        """Emits APP_LOAD_COMPLETED after starting apps."""
        mock_registry.manifests = {"app_a": MagicMock()}
        mock_registry.active_manifests = {}
        mock_registry.get_snapshot = Mock(return_value=MagicMock(running_count=0, failed_count=0))

        await lifecycle_service.bootstrap_apps()

        calls = mock_hassette.send_event.call_args_list
        completed_calls = [call for call in calls if call[0][0].topic == Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED]
        assert len(completed_calls) == 1

    async def test_handles_crash(self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock) -> None:
        """Calls handle_crash and re-raises on exception."""
        mock_registry.manifests = {"app_a": MagicMock()}
        # boundary-exempt: collaborator of bootstrap_apps
        lifecycle_service.resolve_only_app = AsyncMock(side_effect=RuntimeError("crash"))
        lifecycle_service.handle_crash = AsyncMock()  # boundary-exempt: collaborator of bootstrap_apps

        with pytest.raises(RuntimeError, match="crash"):
            await lifecycle_service.bootstrap_apps()

        lifecycle_service.handle_crash.assert_called_once()


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
    def test_returns_true_when_manifest_autostart_true(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """Returns True when manifest exists and autostart=True."""
        manifest = MagicMock()
        manifest.autostart = True
        mock_registry.get_manifest = Mock(return_value=manifest)

        assert lifecycle_service.should_autostart("app_a") is True

    def test_returns_false_when_manifest_autostart_false(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """Returns False when manifest exists and autostart=False."""
        manifest = MagicMock()
        manifest.autostart = False
        mock_registry.get_manifest = Mock(return_value=manifest)

        assert lifecycle_service.should_autostart("app_a") is False

    def test_returns_false_when_manifest_missing(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """Returns False when manifest does not exist."""
        mock_registry.get_manifest = Mock(return_value=None)

        assert lifecycle_service.should_autostart("unknown_app") is False


class TestShouldAutoReconcile:
    def test_returns_true_when_app_running(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """Returns True for a running app regardless of autostart."""
        manifest = MagicMock()
        manifest.autostart = False
        mock_registry.get_manifest = Mock(return_value=manifest)
        mock_registry.apps = {"app_a": {0: MagicMock()}}

        assert lifecycle_service.should_auto_reconcile("app_a") is True

    def test_returns_true_when_app_not_running_but_autostart_true(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """Returns True for a non-running app when autostart=True."""
        manifest = MagicMock()
        manifest.autostart = True
        mock_registry.get_manifest = Mock(return_value=manifest)
        mock_registry.apps = {}

        assert lifecycle_service.should_auto_reconcile("app_a") is True

    def test_returns_false_when_app_not_running_and_autostart_false(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """Returns False for a non-running app when autostart=False."""
        manifest = MagicMock()
        manifest.autostart = False
        mock_registry.get_manifest = Mock(return_value=manifest)
        mock_registry.apps = {}

        assert lifecycle_service.should_auto_reconcile("app_a") is False


class TestApplyChangesGating:
    async def test_new_apps_autostart_false_not_started(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """new_apps with autostart=False are skipped in apply_changes."""
        manifest = MagicMock()
        manifest.autostart = False
        mock_registry.get_manifest = Mock(return_value=manifest)
        mock_registry.apps = {}
        lifecycle_service.start_app = AsyncMock()  # boundary-exempt: collaborator of apply_changes

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
        mock_registry.apps = {}
        lifecycle_service.start_app = AsyncMock()  # boundary-exempt: collaborator of apply_changes

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
        mock_registry.apps = {"app_a": {0: MagicMock()}}
        lifecycle_service.reload_app = AsyncMock()  # boundary-exempt: collaborator of apply_changes

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
        mock_registry.apps = {}
        lifecycle_service.reload_app = AsyncMock()  # boundary-exempt: collaborator of apply_changes

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
        mock_registry.apps = {"app_a": {0: MagicMock()}}
        lifecycle_service.reload_app = AsyncMock()  # boundary-exempt: collaborator of apply_changes

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
        mock_registry.apps = {}
        lifecycle_service.reload_app = AsyncMock()  # boundary-exempt: collaborator of apply_changes

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
        mock_registry.apps = {}
        lifecycle_service.stop_app = AsyncMock()  # boundary-exempt: collaborator of apply_changes

        changes = ChangeSet(
            orphans=frozenset({"app_a"}),
            new_apps=frozenset(),
            reimport_apps=frozenset(),
            reload_apps=frozenset(),
        )
        await lifecycle_service.apply_changes(changes)

        lifecycle_service.stop_app.assert_called_once_with("app_a")
