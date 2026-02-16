"""Tests for AppRegistry."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from hassette.core.app_registry import (
    AppInstanceInfo,
    AppRegistry,
    AppStatusSnapshot,
)
from hassette.types.enums import BlockReason, ResourceStatus


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
            AppInstanceInfo("app1", 0, "app1.0", "App1", ResourceStatus.RUNNING),
            AppInstanceInfo("app2", 0, "app2.0", "App2", ResourceStatus.RUNNING),
        ]
        failed = [
            AppInstanceInfo("app3", 0, "app3.0", "App3", ResourceStatus.FAILED, error=Exception("test")),
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
        assert info.status == ResourceStatus.RUNNING

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
        assert info.status == ResourceStatus.FAILED
        assert info.error is error
        assert info.error_message == "startup failed"

    def test_get_snapshot_with_only_app(self, registry: AppRegistry) -> None:
        """Test snapshot includes only_app."""
        registry.set_only_app("special_app")

        snapshot = registry.get_snapshot()

        assert snapshot.only_app == "special_app"

    def test_get_snapshot_preserves_resource_status(self, registry: AppRegistry) -> None:
        """Test that snapshot uses ResourceStatus directly from app."""
        app = MagicMock()
        app.app_config.instance_name = "test"
        app.class_name = "Test"
        app.status = ResourceStatus.STARTING
        registry.register_app("app", 0, app)

        snapshot = registry.get_snapshot()

        assert snapshot.running[0].status == ResourceStatus.STARTING

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

    # --- Enabled manifests tests ---

    def test_enabled_manifests(self, registry: AppRegistry) -> None:
        """Test enabled_manifests returns only enabled apps."""
        enabled = MagicMock()
        enabled.enabled = True
        disabled = MagicMock()
        disabled.enabled = False

        registry.set_manifests({"app1": enabled, "app2": disabled})

        result = registry.enabled_manifests
        assert "app1" in result
        assert "app2" not in result


class TestBlockedApps:
    """Tests for blocked apps tracking."""

    @pytest.fixture
    def registry(self) -> AppRegistry:
        return AppRegistry()

    def test_block_app(self, registry: AppRegistry) -> None:
        """Block an app and verify it is tracked."""
        registry.block_app("my_app", BlockReason.ONLY_APP)

        assert "my_app" in registry._blocked_apps
        assert registry._blocked_apps["my_app"] == BlockReason.ONLY_APP

    def test_unblock_apps(self, registry: AppRegistry) -> None:
        """Block two apps with ONLY_APP, unblock, verify both returned and dict is empty."""
        registry.block_app("app1", BlockReason.ONLY_APP)
        registry.block_app("app2", BlockReason.ONLY_APP)

        unblocked = registry.unblock_apps(BlockReason.ONLY_APP)

        assert unblocked == {"app1", "app2"}
        assert len(registry._blocked_apps) == 0

    def test_unblock_apps_returns_empty_when_none_blocked(self, registry: AppRegistry) -> None:
        """Unblocking with no blocked apps returns empty set."""
        unblocked = registry.unblock_apps(BlockReason.ONLY_APP)

        assert unblocked == set()

    def test_clear_all_clears_blocked(self, registry: AppRegistry) -> None:
        """Verify clear_all also clears _blocked_apps."""
        mock_app = MagicMock()
        registry.register_app("app1", 0, mock_app)
        registry.record_failure("app2", 0, Exception("error"))
        registry.block_app("app3", BlockReason.ONLY_APP)

        registry.clear_all()

        assert len(registry.apps) == 0
        assert registry.get_snapshot().failed_count == 0
        assert len(registry._blocked_apps) == 0


class TestAppRegistryGetFullSnapshot:
    """Unit tests for get_full_snapshot() status derivation."""

    def _make_registry(self) -> AppRegistry:
        return AppRegistry()

    def _make_manifest_obj(self, app_key: str, enabled: bool = True, auto_loaded: bool = False) -> SimpleNamespace:
        """Build a minimal AppManifest-like object for the registry."""
        return SimpleNamespace(
            app_key=app_key,
            class_name=f"{app_key.title().replace('_', '')}",
            display_name=app_key.replace("_", " ").title(),
            filename=f"{app_key}.py",
            enabled=enabled,
            auto_loaded=auto_loaded,
        )

    def _make_app_instance(self, app_key: str, index: int = 0) -> SimpleNamespace:
        """Build a minimal App-like object for the registry."""
        class_name = app_key.title().replace("_", "")
        instance_name = f"{app_key}.{index}"
        return SimpleNamespace(
            app_config=SimpleNamespace(instance_name=instance_name),
            class_name=class_name,
            status=ResourceStatus.RUNNING,
            unique_name=f"{class_name}.{instance_name}",
        )

    def test_empty_manifests(self) -> None:
        reg = self._make_registry()
        snap = reg.get_full_snapshot()
        assert snap.total == 0
        assert snap.manifests == []

    def test_running_app(self) -> None:
        reg = self._make_registry()
        reg.set_manifests({"my_app": self._make_manifest_obj("my_app")})
        reg.register_app("my_app", 0, self._make_app_instance("my_app"))
        snap = reg.get_full_snapshot()
        assert snap.total == 1
        assert snap.running == 1
        assert snap.manifests[0].status == "running"
        assert snap.manifests[0].instance_count == 1

    def test_stopped_app(self) -> None:
        reg = self._make_registry()
        reg.set_manifests({"my_app": self._make_manifest_obj("my_app")})
        # No instances registered — status is "stopped"
        snap = reg.get_full_snapshot()
        assert snap.stopped == 1
        assert snap.manifests[0].status == "stopped"

    def test_failed_app(self) -> None:
        reg = self._make_registry()
        reg.set_manifests({"my_app": self._make_manifest_obj("my_app")})
        reg.record_failure("my_app", 0, RuntimeError("init error"))
        snap = reg.get_full_snapshot()
        assert snap.failed == 1
        assert snap.manifests[0].status == "failed"
        assert snap.manifests[0].error_message == "init error"

    def test_disabled_app(self) -> None:
        reg = self._make_registry()
        reg.set_manifests({"my_app": self._make_manifest_obj("my_app", enabled=False)})
        snap = reg.get_full_snapshot()
        assert snap.disabled == 1
        assert snap.manifests[0].status == "disabled"

    def test_blocked_app(self) -> None:
        reg = self._make_registry()
        reg.set_manifests({"my_app": self._make_manifest_obj("my_app")})
        reg.block_app("my_app", BlockReason.ONLY_APP)
        snap = reg.get_full_snapshot()
        assert snap.blocked == 1
        assert snap.manifests[0].status == "blocked"
        assert snap.manifests[0].block_reason == "only_app"

    def test_mixed_states(self) -> None:
        reg = self._make_registry()
        reg.set_manifests(
            {
                "running_app": self._make_manifest_obj("running_app"),
                "stopped_app": self._make_manifest_obj("stopped_app"),
                "failed_app": self._make_manifest_obj("failed_app"),
                "disabled_app": self._make_manifest_obj("disabled_app", enabled=False),
                "blocked_app": self._make_manifest_obj("blocked_app"),
            }
        )
        reg.register_app("running_app", 0, self._make_app_instance("running_app"))
        reg.record_failure("failed_app", 0, ValueError("bad config"))
        reg.block_app("blocked_app", BlockReason.ONLY_APP)

        snap = reg.get_full_snapshot()
        assert snap.total == 5
        assert snap.running == 1
        assert snap.stopped == 1
        assert snap.failed == 1
        assert snap.disabled == 1
        assert snap.blocked == 1

        statuses = {m.app_key: m.status for m in snap.manifests}
        assert statuses["running_app"] == "running"
        assert statuses["stopped_app"] == "stopped"
        assert statuses["failed_app"] == "failed"
        assert statuses["disabled_app"] == "disabled"
        assert statuses["blocked_app"] == "blocked"

    def test_disabled_takes_priority_over_running(self) -> None:
        """Even if an app has running instances, disabled=False should win."""
        reg = self._make_registry()
        reg.set_manifests({"my_app": self._make_manifest_obj("my_app", enabled=False)})
        reg.register_app("my_app", 0, self._make_app_instance("my_app"))
        snap = reg.get_full_snapshot()
        # Disabled takes priority
        assert snap.manifests[0].status == "disabled"
