"""Tests for AppRegistry."""

from unittest.mock import MagicMock

import pytest

from hassette.core.app_registry import (
    AppInstanceInfo,
    AppInstanceStatus,
    AppRegistry,
    AppStatusSnapshot,
)
from hassette.types.enums import ResourceStatus


class TestAppInstanceStatus:
    def test_status_values_exist(self) -> None:
        """Verify all expected status values exist."""
        assert AppInstanceStatus.PENDING
        assert AppInstanceStatus.INITIALIZING
        assert AppInstanceStatus.RUNNING
        assert AppInstanceStatus.FAILED
        assert AppInstanceStatus.STOPPING
        assert AppInstanceStatus.STOPPED


class TestAppStatusSnapshot:
    def test_empty_snapshot(self) -> None:
        """Test snapshot with no apps."""
        snapshot = AppStatusSnapshot()
        assert snapshot.running == []
        assert snapshot.failed == []
        assert snapshot.only_app is None
        assert snapshot.total_count == 0
        assert snapshot.running_count == 0
        assert snapshot.failed_count == 0

    def test_snapshot_counts(self) -> None:
        """Test snapshot count properties."""
        running = [
            AppInstanceInfo("app1", 0, "app1.0", "App1", AppInstanceStatus.RUNNING),
            AppInstanceInfo("app2", 0, "app2.0", "App2", AppInstanceStatus.RUNNING),
        ]
        failed = [
            AppInstanceInfo("app3", 0, "app3.0", "App3", AppInstanceStatus.FAILED, error=Exception("test")),
        ]
        snapshot = AppStatusSnapshot(running=running, failed=failed, only_app="app1")

        assert snapshot.running_count == 2
        assert snapshot.failed_count == 1
        assert snapshot.total_count == 3
        assert snapshot.only_app == "app1"


class TestAppRegistry:
    @pytest.fixture
    def registry(self) -> AppRegistry:
        return AppRegistry()

    @pytest.fixture
    def mock_app(self) -> MagicMock:
        """Create a mock app with required attributes."""
        app = MagicMock()
        app.app_config.instance_name = "test_instance"
        app.class_name = "TestApp"
        app.status = ResourceStatus.RUNNING
        return app

    @pytest.fixture
    def mock_manifest(self) -> MagicMock:
        """Create a mock manifest."""
        manifest = MagicMock()
        manifest.class_name = "TestApp"
        return manifest

    # --- Registration tests ---

    def test_register_app(self, registry: AppRegistry, mock_app: MagicMock) -> None:
        """Test registering an app."""
        registry.register_app("my_app", 0, mock_app)

        assert "my_app" in registry.apps
        assert registry.apps["my_app"][0] is mock_app

    def test_register_multiple_instances(self, registry: AppRegistry) -> None:
        """Test registering multiple instances of the same app."""
        app1 = MagicMock()
        app2 = MagicMock()

        registry.register_app("my_app", 0, app1)
        registry.register_app("my_app", 1, app2)

        assert len(registry.apps["my_app"]) == 2
        assert registry.apps["my_app"][0] is app1
        assert registry.apps["my_app"][1] is app2

    # --- Unregistration tests ---

    def test_unregister_app_all_instances(self, registry: AppRegistry, mock_app: MagicMock) -> None:
        """Test unregistering all instances of an app."""
        registry.register_app("my_app", 0, mock_app)
        registry.register_app("my_app", 1, mock_app)

        removed = registry.unregister_app("my_app")

        assert removed is not None
        assert len(removed) == 2
        assert "my_app" not in registry.apps

    def test_unregister_app_single_instance(self, registry: AppRegistry, mock_app: MagicMock) -> None:
        """Test unregistering a single instance."""
        app1 = MagicMock()
        app2 = MagicMock()
        registry.register_app("my_app", 0, app1)
        registry.register_app("my_app", 1, app2)

        removed = registry.unregister_app("my_app", index=0)

        assert removed == {0: app1}
        assert 0 not in registry.apps["my_app"]
        assert 1 in registry.apps["my_app"]

    def test_unregister_nonexistent_app(self, registry: AppRegistry) -> None:
        """Test unregistering an app that doesn't exist."""
        removed = registry.unregister_app("nonexistent")
        assert removed is None

    def test_unregister_nonexistent_index(self, registry: AppRegistry, mock_app: MagicMock) -> None:
        """Test unregistering a nonexistent index."""
        registry.register_app("my_app", 0, mock_app)

        removed = registry.unregister_app("my_app", index=99)

        assert removed is None

    # --- Failure tracking tests ---

    def test_record_failure(self, registry: AppRegistry) -> None:
        """Test recording a failure."""
        error = Exception("test error")
        registry.record_failure("my_app", 0, error)

        snapshot = registry.get_snapshot()

        assert "my_app" in snapshot.failed_apps

    def test_record_multiple_failures(self, registry: AppRegistry) -> None:
        """Test recording multiple failures for the same app."""
        error1 = Exception("error 1")
        error2 = Exception("error 2")

        registry.record_failure("my_app", 0, error1)
        registry.record_failure("my_app", 1, error2)

        apps_dict = registry.get_snapshot().apps_dict

        assert ("my_app", 0) in apps_dict
        assert ("my_app", 1) in apps_dict

    def test_clear_failures_single_app(self, registry: AppRegistry) -> None:
        """Test clearing failures for a single app."""
        registry.record_failure("app1", 0, Exception("error"))
        registry.record_failure("app2", 0, Exception("error"))

        registry.clear_failures("app1")

        snapshot = registry.get_snapshot()

        assert "app1" not in snapshot.failed_apps
        assert "app2" in snapshot.failed_apps

    def test_clear_failures_all(self, registry: AppRegistry) -> None:
        """Test clearing all failures."""
        registry.record_failure("app1", 0, Exception("error"))
        registry.record_failure("app2", 0, Exception("error"))

        registry.clear_failures()

        assert registry.get_snapshot().failed_count == 0

    # --- Query tests ---

    def test_get_existing_app(self, registry: AppRegistry, mock_app: MagicMock) -> None:
        """Test getting an existing app."""
        registry.register_app("my_app", 0, mock_app)

        result = registry.get("my_app", 0)

        assert result is mock_app

    def test_get_nonexistent_app(self, registry: AppRegistry) -> None:
        """Test getting a nonexistent app."""
        result = registry.get("nonexistent", 0)
        assert result is None

    def test_get_default_index(self, registry: AppRegistry, mock_app: MagicMock) -> None:
        """Test that get() defaults to index 0."""
        registry.register_app("my_app", 0, mock_app)

        result = registry.get("my_app")

        assert result is mock_app

    def test_all_apps(self, registry: AppRegistry) -> None:
        """Test getting all apps."""
        app1 = MagicMock()
        app2 = MagicMock()
        app3 = MagicMock()

        registry.register_app("app1", 0, app1)
        registry.register_app("app2", 0, app2)
        registry.register_app("app2", 1, app3)

        all_apps = registry.all_apps()

        assert len(all_apps) == 3
        assert app1 in all_apps
        assert app2 in all_apps
        assert app3 in all_apps

    def test_get_apps_by_key(self, registry: AppRegistry, mock_app: MagicMock) -> None:
        """Test getting all instances for a key."""
        app1 = MagicMock()
        app2 = MagicMock()
        registry.register_app("my_app", 0, app1)
        registry.register_app("my_app", 1, app2)

        result = registry.get_apps_by_key("my_app")

        assert result == {0: app1, 1: app2}
        # Verify it's a copy
        result[99] = MagicMock()
        assert 99 not in registry.apps["my_app"]

    # --- Snapshot tests ---

    def test_get_snapshot_empty(self, registry: AppRegistry) -> None:
        """Test snapshot with no apps."""
        snapshot = registry.get_snapshot()

        assert snapshot.running == []
        assert snapshot.failed == []
        assert snapshot.only_app is None

    def test_get_snapshot_with_running_apps(self, registry: AppRegistry, mock_app: MagicMock) -> None:
        """Test snapshot includes running apps."""
        mock_app.status = ResourceStatus.RUNNING
        registry.register_app("my_app", 0, mock_app)

        snapshot = registry.get_snapshot()

        assert len(snapshot.running) == 1
        info = snapshot.running[0]
        assert info.app_key == "my_app"
        assert info.index == 0
        assert info.instance_name == "test_instance"
        assert info.class_name == "TestApp"
        assert info.status == AppInstanceStatus.RUNNING

    def test_get_snapshot_with_failed_apps(self, registry: AppRegistry, mock_manifest: MagicMock) -> None:
        """Test snapshot includes failed apps."""
        error = Exception("startup failed")
        registry.set_manifests({"my_app": mock_manifest})
        registry.record_failure("my_app", 0, error)

        snapshot = registry.get_snapshot()

        assert len(snapshot.failed) == 1
        info = snapshot.failed[0]
        assert info.app_key == "my_app"
        assert info.index == 0
        assert info.status == AppInstanceStatus.FAILED
        assert info.error is error
        assert info.error_message == "startup failed"

    def test_get_snapshot_with_only_app(self, registry: AppRegistry) -> None:
        """Test snapshot includes only_app."""
        registry.set_only_app("special_app")

        snapshot = registry.get_snapshot()

        assert snapshot.only_app == "special_app"

    def test_get_snapshot_maps_resource_status(self, registry: AppRegistry) -> None:
        """Test that ResourceStatus values are correctly mapped."""
        status_mapping = [
            (ResourceStatus.NOT_STARTED, AppInstanceStatus.PENDING),
            (ResourceStatus.STARTING, AppInstanceStatus.INITIALIZING),
            (ResourceStatus.RUNNING, AppInstanceStatus.RUNNING),
            (ResourceStatus.STOPPED, AppInstanceStatus.STOPPED),
            (ResourceStatus.FAILED, AppInstanceStatus.FAILED),
            (ResourceStatus.CRASHED, AppInstanceStatus.FAILED),
        ]

        for resource_status, expected_app_status in status_mapping:
            registry._apps.clear()
            app = MagicMock()
            app.app_config.instance_name = "test"
            app.class_name = "Test"
            app.status = resource_status
            registry.register_app("app", 0, app)

            snapshot = registry.get_snapshot()

            assert snapshot.running[0].status == expected_app_status, (
                f"Expected {resource_status} to map to {expected_app_status}"
            )

    # --- Clear all tests ---

    def test_clear_all(self, registry: AppRegistry, mock_app: MagicMock) -> None:
        """Test clearing all apps and failures."""
        registry.register_app("app1", 0, mock_app)
        registry.record_failure("app2", 0, Exception("error"))

        registry.clear_all()

        assert len(registry.apps) == 0
        assert registry.get_snapshot().failed_count == 0

    # --- Manifest and only_app tests ---

    def test_set_manifests(self, registry: AppRegistry, mock_manifest: MagicMock) -> None:
        """Test setting manifests."""
        manifests = {"app1": mock_manifest}
        registry.set_manifests(manifests)

        assert registry.manifests == manifests
        # Verify it's a copy
        manifests["app2"] = MagicMock()
        assert "app2" not in registry.manifests

    def test_set_only_app(self, registry: AppRegistry) -> None:
        """Test setting only_app."""
        registry.set_only_app("my_app")
        assert registry.only_app == "my_app"

        registry.set_only_app(None)
        assert registry.only_app is None
