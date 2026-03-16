"""Unit tests for AppLifecycleService."""

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.types import Topic
from hassette.types.enums import BlockReason, ResourceStatus


def _make_spawn_mock() -> AsyncMock:
    """Create a mock for task_bucket.spawn that properly closes passed coroutines.

    spawn() returns an asyncio.Task (awaitable), so the mock must be async.
    The side_effect closes the coroutine to prevent 'was never awaited' warnings.
    """

    async def _spawn_side_effect(coro, **_kwargs: object) -> None:
        coro.close()

    return AsyncMock(side_effect=_spawn_side_effect)


@pytest.fixture
def mock_hassette() -> MagicMock:
    """Create a mock Hassette instance with config."""
    hassette = MagicMock()
    hassette.config = MagicMock()
    hassette.config.app_startup_timeout_seconds = 30
    hassette.config.app_shutdown_timeout_seconds = 10
    hassette.config.dev_mode = True
    hassette.config.allow_only_app_in_prod = False
    hassette.config.allow_reload_in_prod = False
    hassette.config.app_handler_log_level = "DEBUG"
    hassette.config.app_manifests = {}
    hassette.config.data_dir = Path("/tmp/hassette-test")
    hassette.send_event = AsyncMock()
    hassette.wait_for_ready = AsyncMock(return_value=True)
    return hassette


@pytest.fixture
def mock_registry() -> MagicMock:
    """Create a mock AppRegistry instance."""
    registry = MagicMock()
    registry.record_failure = Mock()
    registry.all_apps = Mock(return_value=[])
    registry.clear_all = Mock()
    registry.get_manifest = Mock(return_value=None)
    registry.get_apps_by_key = Mock(return_value={})
    registry.register_app = Mock()
    registry.unregister_app = Mock(return_value=None)
    registry.set_manifests = Mock()
    registry.set_only_app = Mock()
    registry.apps = {}
    registry.manifests = {}
    registry.enabled_manifests = {}
    registry.active_manifests = {}
    registry.only_app = None
    registry.get_snapshot = Mock()
    registry.block_app = Mock()
    registry.unblock_apps = Mock(return_value=set())
    return registry


@pytest.fixture
def mock_factory() -> MagicMock:
    """Create a mock AppFactory."""
    factory = MagicMock()
    factory.create_instances = Mock()
    factory.check_only_app_decorator = Mock(return_value=False)
    return factory


@pytest.fixture
def mock_manifest() -> MagicMock:
    """Create a mock AppManifest instance."""
    manifest = MagicMock()
    manifest.class_name = "TestApp"
    manifest.app_key = "test_app"
    manifest.full_path = Path("/apps/test_app.py")
    manifest.display_name = "Test App"
    manifest.enabled = True
    return manifest


@pytest.fixture
def mock_app_instance() -> AsyncMock:
    """Create a mock App instance."""
    app = AsyncMock()
    app.app_config = MagicMock()
    app.app_config.instance_name = "test_instance"
    app.status = ResourceStatus.NOT_STARTED
    app.class_name = "MockApp"
    app.initialize = AsyncMock()
    app.shutdown = AsyncMock()
    app.mark_ready = Mock()
    app.logger = Mock()
    return app


@pytest.fixture
def lifecycle_service(
    mock_hassette: MagicMock, mock_registry: MagicMock, mock_factory: MagicMock
) -> AppLifecycleService:
    """Create an AppLifecycleService with mocked dependencies."""
    logging.getLogger("hassette").propagate = True

    with (
        patch("hassette.core.app_lifecycle_service.AppFactory", return_value=mock_factory),
        patch("hassette.core.app_lifecycle_service.AppChangeDetector"),
    ):
        service = AppLifecycleService(mock_hassette, parent=None, registry=mock_registry)
    service.factory = mock_factory
    return service


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

    def test_creates_bus_child(
        self, mock_hassette: MagicMock, mock_registry: MagicMock, mock_factory: MagicMock
    ) -> None:
        """Verify constructor creates a Bus as a child resource."""
        with (
            patch("hassette.core.app_lifecycle_service.AppFactory", return_value=mock_factory),
            patch("hassette.core.app_lifecycle_service.AppChangeDetector"),
        ):
            service = AppLifecycleService(mock_hassette, parent=None, registry=mock_registry)
        from hassette.bus import Bus

        assert any(isinstance(child, Bus) for child in service.children)


class TestAppLifecycleServiceProperties:
    def test_startup_timeout_from_config(
        self, lifecycle_service: AppLifecycleService, mock_hassette: MagicMock
    ) -> None:
        """Returns hassette.config.app_startup_timeout_seconds."""
        assert lifecycle_service.startup_timeout == mock_hassette.config.app_startup_timeout_seconds

    def test_shutdown_timeout_from_config(
        self, lifecycle_service: AppLifecycleService, mock_hassette: MagicMock
    ) -> None:
        """Returns hassette.config.app_shutdown_timeout_seconds."""
        assert lifecycle_service.shutdown_timeout == mock_hassette.config.app_shutdown_timeout_seconds


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
        app1 = AsyncMock()
        app1.app_config = MagicMock(instance_name="instance_0")
        app1.initialize = AsyncMock()
        app1.mark_ready = Mock()

        app2 = AsyncMock()
        app2.app_config = MagicMock(instance_name="instance_1")
        app2.initialize = AsyncMock()
        app2.mark_ready = Mock()

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
        app1 = AsyncMock()
        app1.app_config = MagicMock(instance_name="instance_0")
        app1.initialize = AsyncMock(side_effect=ValueError("Failed"))
        app1.status = ResourceStatus.NOT_STARTED

        app2 = AsyncMock()
        app2.app_config = MagicMock(instance_name="instance_1")
        app2.initialize = AsyncMock()
        app2.mark_ready = Mock()

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
            if call[0][0] == Topic.HASSETTE_EVENT_APP_STATE_CHANGED
            and call[0][1].payload.data.status == ResourceStatus.RUNNING
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
            if call[0][0] == Topic.HASSETTE_EVENT_APP_STATE_CHANGED
            and call[0][1].payload.data.status == ResourceStatus.FAILED
        ]
        assert len(failed_calls) == 1


class TestShutdownInstance:
    async def test_calls_shutdown(self, lifecycle_service: AppLifecycleService, mock_app_instance: AsyncMock) -> None:
        """Calls inst.shutdown()."""
        await lifecycle_service.shutdown_instance(mock_app_instance)

        mock_app_instance.shutdown.assert_called_once()

    async def test_catches_exceptions(
        self, lifecycle_service: AppLifecycleService, mock_app_instance: AsyncMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Logs error but doesn't raise on failure."""
        mock_app_instance.shutdown.side_effect = RuntimeError("Shutdown failed")

        await lifecycle_service.shutdown_instance(mock_app_instance)

        assert "Failed to stop app" in caplog.text

    async def test_emits_stopped_event(
        self, lifecycle_service: AppLifecycleService, mock_app_instance: AsyncMock, mock_hassette: MagicMock
    ) -> None:
        """Emits HASSETTE_EVENT_APP_STATE_CHANGED with STOPPED status."""
        await lifecycle_service.shutdown_instance(mock_app_instance)

        calls = mock_hassette.send_event.call_args_list
        stopped_calls = [
            call
            for call in calls
            if call[0][0] == Topic.HASSETTE_EVENT_APP_STATE_CHANGED
            and call[0][1].payload.data.status == ResourceStatus.STOPPED
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
        assert first_call[0][0] == Topic.HASSETTE_EVENT_APP_STATE_CHANGED
        assert first_call[0][1].payload.data.status == ResourceStatus.STOPPING


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
        completed_calls = [call for call in calls if call[0][0] == Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED]
        assert len(completed_calls) == 1

    async def test_handles_crash(self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock) -> None:
        """Calls handle_crash and re-raises on exception."""
        mock_registry.manifests = {"app_a": MagicMock()}
        lifecycle_service.resolve_only_app = AsyncMock(side_effect=RuntimeError("crash"))
        lifecycle_service.handle_crash = AsyncMock()

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
        """Starts all active apps via asyncio.gather."""
        manifest_a = MagicMock()
        manifest_b = MagicMock()
        mock_registry.active_manifests = {"app_a": manifest_a, "app_b": manifest_b}
        mock_registry.get_manifest = Mock(side_effect=lambda k: {"app_a": manifest_a, "app_b": manifest_b}.get(k))
        mock_registry.get_apps_by_key = Mock(return_value={})
        lifecycle_service.task_bucket = Mock()
        lifecycle_service.task_bucket.spawn = _make_spawn_mock()

        await lifecycle_service.start_apps()

        assert mock_factory.create_instances.call_count == 2


class TestApplyChanges:
    async def test_routes_changes_to_correct_methods(self, lifecycle_service: AppLifecycleService) -> None:
        """Routes orphans/reimport/reload/new to correct methods."""
        lifecycle_service.stop_app = AsyncMock()
        lifecycle_service.reload_app = AsyncMock()
        lifecycle_service.start_app = AsyncMock()

        from hassette.core.app_change_detector import ChangeSet

        changes = ChangeSet(
            orphans=frozenset({"orphan_app"}),
            new_apps=frozenset({"new_app"}),
            reimport_apps=frozenset({"reimport_app"}),
            reload_apps=frozenset({"reload_app"}),
        )

        await lifecycle_service.apply_changes(changes)

        lifecycle_service.stop_app.assert_called_once_with("orphan_app")
        lifecycle_service.reload_app.assert_any_call("reimport_app", force_reload=True)
        lifecycle_service.reload_app.assert_any_call("reload_app")
        lifecycle_service.start_app.assert_called_once_with("new_app")


class TestStartApp:
    async def test_creates_instances_via_factory(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """Calls factory.create_instances with correct app_key."""
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.get_apps_by_key = Mock(return_value={})
        lifecycle_service.task_bucket = Mock()
        lifecycle_service.task_bucket.spawn = _make_spawn_mock()

        await lifecycle_service.start_app("test_app")

        mock_factory.create_instances.assert_called_once_with("test_app", mock_manifest, force_reload=False)

    async def test_emits_not_started_event(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
        mock_app_instance: AsyncMock,
        mock_hassette: MagicMock,
    ) -> None:
        """Emits NOT_STARTED event for each created instance."""
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.get_apps_by_key = Mock(return_value={0: mock_app_instance})
        lifecycle_service.task_bucket = Mock()
        lifecycle_service.task_bucket.spawn = _make_spawn_mock()

        with patch("hassette.core.app_lifecycle_service.get_log_capture_handler", return_value=None):
            await lifecycle_service.start_app("test_app")

        calls = mock_hassette.send_event.call_args_list
        not_started_calls = [
            call
            for call in calls
            if call[0][0] == Topic.HASSETTE_EVENT_APP_STATE_CHANGED
            and call[0][1].payload.data.status == ResourceStatus.NOT_STARTED
        ]
        assert len(not_started_calls) == 1

    async def test_skips_disabled_app(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock, mock_factory: MagicMock
    ) -> None:
        """Skips app when manifest is not found (disabled or unknown)."""
        mock_registry.get_manifest = Mock(return_value=None)

        await lifecycle_service.start_app("disabled_app")

        mock_factory.create_instances.assert_not_called()

    async def test_handles_factory_load_error(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """Handles exception from factory.create_instances gracefully."""
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_factory.create_instances.side_effect = RuntimeError("Load failed")

        # Should not raise
        await lifecycle_service.start_app("test_app")

        mock_registry.get_apps_by_key.assert_not_called()


class TestStopApp:
    async def test_unregisters_and_shuts_down(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """Unregisters app and shuts down its instances."""
        app1 = AsyncMock()
        app1.status = ResourceStatus.RUNNING
        instances = {0: app1}
        mock_registry.unregister_app = Mock(return_value=instances)

        await lifecycle_service.stop_app("test_app")

        mock_registry.unregister_app.assert_called_once_with("test_app")
        app1.shutdown.assert_called_once()

    async def test_warns_if_not_found(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Logs warning when app is not found in registry."""
        mock_registry.unregister_app = Mock(return_value=None)

        await lifecycle_service.stop_app("missing_app")

        assert "Cannot stop app missing_app, not found" in caplog.text


class TestReloadApp:
    async def test_stops_then_starts(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_manifest: MagicMock,
        mock_factory: MagicMock,
    ) -> None:
        """Calls stop_app then start_app."""
        mock_registry.unregister_app = Mock(return_value=None)
        mock_registry.get_manifest = Mock(return_value=mock_manifest)
        mock_registry.get_apps_by_key = Mock(return_value={})
        lifecycle_service.task_bucket = Mock()
        lifecycle_service.task_bucket.spawn = _make_spawn_mock()

        await lifecycle_service.reload_app("test_app")

        mock_registry.unregister_app.assert_called_once_with("test_app")
        mock_factory.create_instances.assert_called_once()


class TestReconcileBlockedApps:
    def test_blocks_non_only_apps(self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock) -> None:
        """Blocks all apps except the only_app."""
        mock_registry.only_app = "app_a"
        mock_registry.enabled_manifests = {"app_a": MagicMock(), "app_b": MagicMock(), "app_c": MagicMock()}
        mock_registry.unblock_apps = Mock(return_value=set())

        lifecycle_service.reconcile_blocked_apps()

        block_calls = mock_registry.block_app.call_args_list
        blocked_keys = {call[0][0] for call in block_calls}
        assert blocked_keys == {"app_b", "app_c"}
        for call in block_calls:
            assert call[0][1] == BlockReason.ONLY_APP

    def test_unblocks_when_only_app_cleared(
        self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock
    ) -> None:
        """Unblocks previously blocked apps when only_app is None."""
        mock_registry.only_app = None
        mock_registry.enabled_manifests = {"app_a": MagicMock(), "app_b": MagicMock()}
        mock_registry.unblock_apps = Mock(return_value={"app_b"})

        result = lifecycle_service.reconcile_blocked_apps()

        mock_registry.unblock_apps.assert_called_once_with(BlockReason.ONLY_APP)
        mock_registry.block_app.assert_not_called()
        assert result == {"app_b"}


class TestResolveOnlyApp:
    async def test_sets_only_app_when_decorated(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        """Sets only_app filter when a decorated app is found."""
        mock_registry.active_manifests = {"test_app": mock_manifest}
        mock_factory.check_only_app_decorator = Mock(return_value=True)

        await lifecycle_service.resolve_only_app()

        mock_registry.set_only_app.assert_called_with("test_app")

    async def test_clears_only_app_when_none_decorated(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        """Clears only_app filter when no decorated app is found."""
        mock_registry.active_manifests = {"test_app": mock_manifest}
        mock_factory.check_only_app_decorator = Mock(return_value=False)

        await lifecycle_service.resolve_only_app()

        mock_registry.set_only_app.assert_called_with(None)

    async def test_disallows_only_app_in_prod_by_default(
        self,
        lifecycle_service: AppLifecycleService,
        mock_hassette: MagicMock,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        """Disallows only_app in production mode when not explicitly allowed."""
        mock_hassette.config.dev_mode = False
        mock_hassette.config.allow_only_app_in_prod = False
        mock_registry.active_manifests = {"test_app": mock_manifest}
        mock_factory.check_only_app_decorator = Mock(return_value=True)

        await lifecycle_service.resolve_only_app()

        mock_registry.set_only_app.assert_called_with(None)


class TestRefreshConfig:
    async def test_reloads_config_and_returns_before_after(
        self, lifecycle_service: AppLifecycleService, mock_hassette: MagicMock, mock_registry: MagicMock
    ) -> None:
        """Calls config.reload() and returns original and current manifests."""
        manifest1 = MagicMock()
        manifest1.enabled = True
        mock_registry.manifests = {"app_a": manifest1}
        mock_hassette.config.app_manifests = {"app_a": manifest1}
        mock_hassette.config.reload = Mock()

        original, current = await lifecycle_service.refresh_config()

        mock_hassette.config.reload.assert_called_once()
        assert "app_a" in original
        assert "app_a" in current


class TestSetAppsConfigs:
    def test_sets_manifests_on_registry(self, lifecycle_service: AppLifecycleService, mock_registry: MagicMock) -> None:
        """Calls registry.set_manifests with the provided config."""
        manifests = {"app_a": MagicMock()}

        lifecycle_service.set_apps_configs(manifests)

        mock_registry.set_manifests.assert_called_once()
        mock_registry.set_only_app.assert_called_with(None)
