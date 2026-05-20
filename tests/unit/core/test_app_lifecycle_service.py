"""Unit tests for AppLifecycleService."""

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from hassette.bus import Bus
from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.test_utils.mock_hassette import make_mock_hassette
from hassette.types import Topic
from hassette.types.enums import ResourceStatus


@pytest.fixture
def mock_hassette() -> AsyncMock:
    """Create a mock Hassette instance with config."""
    hassette = make_mock_hassette(
        sealed=False,
        dev_mode=True,
        logging={"app_handler": "DEBUG"},
        lifecycle={"app_startup_timeout_seconds": 30},
    )
    hassette.send_event = AsyncMock()
    hassette.command_executor = MagicMock()
    hassette.command_executor.reconcile_registrations = AsyncMock()
    hassette.bus_service = MagicMock()
    hassette.bus_service.await_registrations_complete = AsyncMock()
    hassette.bus_service.router = MagicMock()
    hassette.bus_service.router.get_listeners_by_owner = Mock(return_value=[])
    hassette.scheduler_service = MagicMock()
    hassette.scheduler_service.await_registrations_complete = AsyncMock()
    hassette.session_id = 1
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
    app.bus = MagicMock()
    app.bus.get_listeners = Mock(return_value=[])
    app.bus.owner_id = "MockApp.test_instance"
    app.scheduler = MagicMock()
    app.scheduler.get_job_db_ids = Mock(return_value=[])
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

        assert any(isinstance(child, Bus) for child in service.children)


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
        app1 = AsyncMock()
        app1.app_config = MagicMock(instance_name="instance_0")
        app1.initialize = AsyncMock()
        app1.mark_ready = Mock()
        app1.bus = MagicMock()
        app1.bus.get_listeners = Mock(return_value=[])
        app1.bus.owner_id = "TestApp.instance_0"
        app1.scheduler = MagicMock()
        app1.scheduler.get_job_db_ids = Mock(return_value=[])

        app2 = AsyncMock()
        app2.app_config = MagicMock(instance_name="instance_1")
        app2.initialize = AsyncMock()
        app2.mark_ready = Mock()
        app2.bus = MagicMock()
        app2.bus.get_listeners = Mock(return_value=[])
        app2.bus.owner_id = "TestApp.instance_1"
        app2.scheduler = MagicMock()
        app2.scheduler.get_job_db_ids = Mock(return_value=[])

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
        app1.bus = MagicMock()
        app1.bus.get_listeners = Mock(return_value=[])
        app1.bus.owner_id = "TestApp.instance_0"
        app1.scheduler = MagicMock()
        app1.scheduler.get_job_db_ids = Mock(return_value=[])

        app2 = AsyncMock()
        app2.app_config = MagicMock(instance_name="instance_1")
        app2.initialize = AsyncMock()
        app2.mark_ready = Mock()
        app2.bus = MagicMock()
        app2.bus.get_listeners = Mock(return_value=[])
        app2.bus.owner_id = "TestApp.instance_1"
        app2.scheduler = MagicMock()
        app2.scheduler.get_job_db_ids = Mock(return_value=[])

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
        self, lifecycle_service: AppLifecycleService, mock_app_instance: AsyncMock, mock_hassette: MagicMock
    ) -> None:
        """Doesn't raise on shutdown failure; emits FAILED state event."""
        mock_app_instance.shutdown.side_effect = RuntimeError("Shutdown failed")

        await lifecycle_service.shutdown_instance(mock_app_instance)

        calls = mock_hassette.send_event.call_args_list
        failed_calls = [
            call
            for call in calls
            if call[0][0] == Topic.HASSETTE_EVENT_APP_STATE_CHANGED
            and call[0][1].payload.data.status == ResourceStatus.FAILED
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

        await lifecycle_service.start_apps()

        assert mock_factory.create_instances.call_count == 2
