"""Unit tests for AppLifecycleManager."""

from unittest.mock import AsyncMock, Mock, PropertyMock, patch

import pytest

from hassette.app.app import App
from hassette.core.app_lifecycle import AppLifecycleManager
from hassette.core.app_registry import AppRegistry
from hassette.types.enums import ResourceStatus


@pytest.fixture
def mock_hassette():
    """Create a mock Hassette instance with config."""
    hassette = Mock()
    hassette.config = Mock()
    hassette.config.app_startup_timeout_seconds = 30
    hassette.config.app_shutdown_timeout_seconds = 10
    hassette.send_event = AsyncMock()
    return hassette


@pytest.fixture
def mock_registry():
    """Create a mock AppRegistry instance."""
    registry = Mock()
    registry.record_failure = Mock()
    registry.all_apps = Mock(return_value=[])
    registry.clear_all = Mock()
    return registry


@pytest.fixture
def mock_manifest():
    """Create a mock AppManifest instance."""
    manifest = Mock()
    manifest.class_name = "TestApp"
    return manifest


@pytest.fixture
def mock_app_instance():
    """Create a mock App instance."""
    app = AsyncMock()
    app.app_config = Mock()
    app.app_config.instance_name = "test_instance"
    app.status = ResourceStatus.NOT_STARTED
    app.__class__.__name__ = "MockApp"
    app.initialize = AsyncMock()
    app.shutdown = AsyncMock()
    app.cleanup = AsyncMock()
    app.mark_ready = Mock()
    return app


@pytest.fixture
def lifecycle(mock_hassette, mock_registry) -> AppLifecycleManager:
    """Create an AppLifecycleManager instance with mocked dependencies."""
    return AppLifecycleManager(mock_hassette, mock_registry)


class TestAppLifecycleManagerInit:
    def test_init_stores_hassette_and_registry(self, mock_hassette, mock_registry: AppRegistry):
        """Verify constructor stores references correctly."""
        lifecycle = AppLifecycleManager(mock_hassette, mock_registry)

        assert lifecycle.hassette is mock_hassette
        assert lifecycle.registry is mock_registry


class TestAppLifecycleManagerProperties:
    def test_startup_timeout_from_config(self, lifecycle: AppLifecycleManager, mock_hassette):
        """Returns hassette.config.app_startup_timeout_seconds."""
        assert lifecycle.startup_timeout == mock_hassette.config.app_startup_timeout_seconds

    def test_shutdown_timeout_from_config(self, lifecycle: AppLifecycleManager, mock_hassette):
        """Returns hassette.config.app_shutdown_timeout_seconds."""
        assert lifecycle.shutdown_timeout == mock_hassette.config.app_shutdown_timeout_seconds


class TestAppLifecycleManagerInitializeInstances:
    async def test_initialize_instances_success(
        self, lifecycle: AppLifecycleManager, mock_app_instance: App, mock_manifest
    ):
        """Calls initialize() and mark_ready() on each instance."""
        instances = {0: mock_app_instance}

        await lifecycle.initialize_instances("test_app", instances, mock_manifest)

        mock_app_instance.initialize.assert_called_once()
        mock_app_instance.mark_ready.assert_called_once_with(reason="initialized")

    async def test_initialize_instances_multiple(self, lifecycle: AppLifecycleManager, mock_manifest):
        """Initializes all provided instances."""
        app1 = AsyncMock()
        app1.app_config = Mock(instance_name="instance_0")
        app1.initialize = AsyncMock()
        app1.mark_ready = Mock()

        app2 = AsyncMock()
        app2.app_config = Mock(instance_name="instance_1")
        app2.initialize = AsyncMock()
        app2.mark_ready = Mock()

        instances = {0: app1, 1: app2}

        await lifecycle.initialize_instances("test_app", instances, mock_manifest)

        app1.initialize.assert_called_once()
        app1.mark_ready.assert_called_once()
        app2.initialize.assert_called_once()
        app2.mark_ready.assert_called_once()

    async def test_initialize_instances_timeout(
        self, lifecycle: AppLifecycleManager, mock_app_instance: App, mock_manifest, mock_registry: AppRegistry
    ):
        """Sets status to STOPPED and records failure on TimeoutError."""
        mock_app_instance.initialize.side_effect = TimeoutError("Timed out")
        instances = {0: mock_app_instance}

        await lifecycle.initialize_instances("test_app", instances, mock_manifest)

        assert mock_app_instance.status == ResourceStatus.STOPPED
        mock_registry.record_failure.assert_called_once()
        call_args = mock_registry.record_failure.call_args
        assert call_args[0][0] == "test_app"
        assert call_args[0][1] == 0
        assert isinstance(call_args[0][2], TimeoutError)

    async def test_initialize_instances_exception(
        self, lifecycle: AppLifecycleManager, mock_app_instance: App, mock_manifest, mock_registry: AppRegistry
    ):
        """Sets status to STOPPED and records failure on any exception."""
        error = ValueError("Init failed")
        mock_app_instance.initialize.side_effect = error
        instances = {0: mock_app_instance}

        await lifecycle.initialize_instances("test_app", instances, mock_manifest)

        assert mock_app_instance.status == ResourceStatus.STOPPED
        mock_registry.record_failure.assert_called_once_with("test_app", 0, error)

    async def test_initialize_instances_continues_after_failure(
        self, lifecycle: AppLifecycleManager, mock_manifest, mock_registry: AppRegistry
    ):
        """Initializes remaining instances after one fails."""
        app1 = AsyncMock()
        app1.app_config = Mock(instance_name="instance_0")
        app1.initialize = AsyncMock(side_effect=ValueError("Failed"))
        app1.status = ResourceStatus.NOT_STARTED

        app2 = AsyncMock()
        app2.app_config = Mock(instance_name="instance_1")
        app2.initialize = AsyncMock()
        app2.mark_ready = Mock()

        instances = {0: app1, 1: app2}

        await lifecycle.initialize_instances("test_app", instances, mock_manifest)

        # First failed, second should still be initialized
        app1.initialize.assert_called_once()
        app2.initialize.assert_called_once()
        app2.mark_ready.assert_called_once()

    async def test_initialize_instances_logs_success(self, lifecycle, mock_app_instance: App, mock_manifest, caplog):
        """Logs at DEBUG level on successful initialization."""
        instances = {0: mock_app_instance}
        lifecycle.logger.setLevel("DEBUG")
        with caplog.at_level("DEBUG"):
            await lifecycle.initialize_instances("test_app", instances, mock_manifest)

        assert "initialized successfully" in caplog.text

    async def test_initialize_instances_logs_failure(
        self, lifecycle: AppLifecycleManager, mock_app_instance: App, mock_manifest, caplog
    ):
        """Logs at ERROR level on failure."""
        mock_app_instance.initialize.side_effect = ValueError("Failed")
        instances = {0: mock_app_instance}

        await lifecycle.initialize_instances("test_app", instances, mock_manifest)

        assert "Failed to start app" in caplog.text


class TestAppLifecycleManagerShutdownInstance:
    async def test_shutdown_instance_calls_shutdown(self, lifecycle: AppLifecycleManager, mock_app_instance: App):
        """Calls inst.shutdown()."""
        await lifecycle.shutdown_instance(mock_app_instance)

        mock_app_instance.shutdown.assert_called_once()

    async def test_shutdown_instance_catches_exceptions(
        self, lifecycle: AppLifecycleManager, mock_app_instance: App, caplog
    ):
        """Logs error but doesn't raise on failure."""
        mock_app_instance.shutdown.side_effect = RuntimeError("Shutdown failed")

        # Should not raise
        await lifecycle.shutdown_instance(mock_app_instance)

        assert "Failed to stop app" in caplog.text

    async def test_shutdown_instance_logs_duration(
        self, lifecycle: AppLifecycleManager, mock_app_instance: App, caplog
    ):
        """Logs shutdown duration at DEBUG level."""
        lifecycle.logger.setLevel("DEBUG")
        with caplog.at_level("DEBUG"):
            await lifecycle.shutdown_instance(mock_app_instance)

        assert "Stopped app" in caplog.text


class TestAppLifecycleManagerShutdownInstances:
    async def test_shutdown_instances_empty_dict(self, lifecycle: AppLifecycleManager):
        """Returns early for empty instances dict."""
        # Should not raise and should return quickly
        await lifecycle.shutdown_instances({})

    async def test_shutdown_instances_calls_shutdown_for_each(self, lifecycle: AppLifecycleManager):
        """Calls shutdown_instance() for each app."""
        app1 = AsyncMock()
        app2 = AsyncMock()

        instances = {0: app1, 1: app2}

        await lifecycle.shutdown_instances(instances)

        app1.shutdown.assert_called_once()
        app2.shutdown.assert_called_once()

    async def test_shutdown_instances_logs_count(self, lifecycle: AppLifecycleManager, mock_app_instance: App, caplog):
        """Logs instance count and optional app_key."""
        instances = {0: mock_app_instance}
        lifecycle.logger.setLevel("DEBUG")
        with caplog.at_level("DEBUG"):
            await lifecycle.shutdown_instances(instances)

        assert "Stopping 1 app instances" in caplog.text


class TestAppLifecycleManagerShutdownAll:
    async def test_shutdown_all_shuts_down_all_apps(self, lifecycle: AppLifecycleManager, mock_registry: AppRegistry):
        """Calls shutdown_instance() for each app in registry."""
        app1 = AsyncMock()
        app2 = AsyncMock()

        prop_mock = PropertyMock()
        prop_mock.items.return_value = {"app1": {0: app1}, "app2": {0: app2}}
        prop_mock.values.return_value = [{0: app1}, {0: app2}]

        with patch.object(mock_registry, "apps", prop_mock):
            await lifecycle.shutdown_all()

        app1.shutdown.assert_called_once()
        app2.shutdown.assert_called_once()

    async def test_shutdown_all_clears_registry(self, lifecycle: AppLifecycleManager, mock_registry: AppRegistry):
        """Calls registry.clear_all() after shutdown."""

        with patch.object(mock_registry, "apps", PropertyMock()):
            await lifecycle.shutdown_all()

            mock_registry.clear_all.assert_called_once()

    async def test_shutdown_all_empty_registry(self, lifecycle: AppLifecycleManager, mock_registry: AppRegistry):
        """Handles empty registry gracefully."""
        with patch.object(mock_registry, "apps", PropertyMock()):
            # Should not raise
            await lifecycle.shutdown_all()

            mock_registry.clear_all.assert_called_once()
