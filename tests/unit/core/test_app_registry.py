"""Unit tests for AppRegistry core registration and its AppStatusSnapshot counts.

Covers `AppStatusSnapshot` itself and `AppRegistry`, including `get_snapshot()`.
The `get_full_snapshot()`, blocking, autostart, and manifest-info tests live in
`test_app_registry_snapshot.py`.
"""

import dataclasses
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from hassette_wire import ResourceStatus

from hassette.core.app_registry import AppRegistry, InstanceEntry
from hassette.schemas.app_snapshots import AppInstanceInfo, AppStatusSnapshot
from tests.support.app_registry_helpers import seed_failed, seed_running

if TYPE_CHECKING:
    from hassette.config.classes import AppManifest


class TestAppStatusSnapshot:
    def test_snapshot_types_are_frozen(self) -> None:
        """Snapshot dataclasses reject field assignment after construction."""
        info = AppInstanceInfo("app1", "app1", "App1", ResourceStatus.RUNNING)
        snapshot = AppStatusSnapshot(instances=(info,))

        with pytest.raises(dataclasses.FrozenInstanceError):
            info.status = ResourceStatus.FAILED  # pyright: ignore[reportAttributeAccessIssue]
        with pytest.raises(dataclasses.FrozenInstanceError):
            snapshot.instances = ()  # pyright: ignore[reportAttributeAccessIssue]

    def test_empty_snapshot(self) -> None:
        """Test snapshot with no apps."""
        snapshot = AppStatusSnapshot()
        assert snapshot.instances == ()
        assert snapshot.only_apps == ()
        assert snapshot.total_count == 0
        assert snapshot.running_count == 0
        assert snapshot.failed_count == 0

    def test_snapshot_counts(self) -> None:
        """Test snapshot count properties."""
        running = [
            AppInstanceInfo("app1", "app1", "App1", ResourceStatus.RUNNING),
            AppInstanceInfo("app2", "app2", "App2", ResourceStatus.RUNNING),
        ]
        failed = [
            AppInstanceInfo("app3", "app3.0", "App3", ResourceStatus.FAILED, error=Exception("test")),
        ]
        snapshot = AppStatusSnapshot(instances=(*running, *failed), only_apps=("app1",))

        assert snapshot.running_count == 2
        assert snapshot.failed_count == 1
        assert snapshot.total_count == 3
        assert snapshot.only_apps == ("app1",)


class TestInstanceEntry:
    def test_holds_app_false_without_app(self) -> None:
        """A failed entry (no App object) is not running."""
        entry = InstanceEntry(app=None, status=ResourceStatus.FAILED, error=RuntimeError("boom"))
        assert entry.holds_app is False

    def test_holds_app_true_with_app(self) -> None:
        """An entry holding an App object is running."""
        entry = InstanceEntry(app=MagicMock(), status=ResourceStatus.RUNNING)
        assert entry.holds_app is True


class TestAppRegistry:
    @pytest.fixture
    def registry(self) -> AppRegistry:
        return AppRegistry()

    @pytest.fixture
    def mock_app(self) -> MagicMock:
        """Create a mock app with required attributes."""
        app = MagicMock()
        app.instance_name = "my_app"
        app.app_config.instance_name = "my_app"
        app.class_name = "TestApp"
        app.status = ResourceStatus.RUNNING
        return app

    @pytest.fixture
    def mock_manifest(self) -> MagicMock:
        """Create a mock manifest."""
        manifest = MagicMock()
        manifest.class_name = "TestApp"
        manifest.app_config = {"instance_name": "test_instance"}
        return manifest

    def test_running_entry_is_readable(self, registry: AppRegistry, mock_app: MagicMock) -> None:
        """A running entry is visible through `in` and `get`."""
        seed_running(registry, "my_app", mock_app)

        assert "my_app" in registry
        assert registry.get("my_app", "my_app") is mock_app

    def test_register_multiple_instances(self, registry: AppRegistry) -> None:
        """Several running instances of one app key are tracked under their own names."""
        app1 = MagicMock(instance_name="my_app")
        app2 = MagicMock(instance_name="my_app_1")

        seed_running(registry, "my_app", app1)
        seed_running(registry, "my_app", app2)

        assert len(registry.get_live_apps("my_app")) == 2
        assert registry.get("my_app", "my_app") is app1
        assert registry.get("my_app", "my_app_1") is app2

    def test_stopped_write_removes_only_that_instance(self, registry: AppRegistry) -> None:
        """A STOPPED write removes its own entry and leaves siblings registered."""
        app1 = MagicMock(instance_name="my_app")
        app2 = MagicMock(instance_name="my_app_1")
        seed_running(registry, "my_app", app1)
        seed_running(registry, "my_app", app2)

        registry.set_status("my_app", "my_app", ResourceStatus.STOPPED)

        assert registry.get("my_app", "my_app") is None
        assert registry.get("my_app", "my_app_1") is app2

    def test_stopping_every_instance_removes_the_app_key(self, registry: AppRegistry, mock_app: MagicMock) -> None:
        """Removing the last entry removes the app key's map too, so iteration never sees an empty one."""
        seed_running(registry, "my_app", mock_app)

        registry.set_status("my_app", "my_app", ResourceStatus.STOPPED)

        assert "my_app" not in registry
        assert "my_app" not in registry._instances

    def test_failed_entry_appears_in_snapshot(self, registry: AppRegistry) -> None:
        """A failed entry appears in the snapshot with its error."""
        error = Exception("test error")
        seed_failed(registry, "my_app", "my_app", error)

        snapshot = registry.get_snapshot()

        assert any(i.app_key == "my_app" and i.error is not None for i in snapshot.instances)

    def test_multiple_failed_entries_for_one_app(self, registry: AppRegistry) -> None:
        """Failures under different names of one app key are kept separately."""
        error1 = Exception("error 1")
        error2 = Exception("error 2")

        seed_failed(registry, "my_app", "my_app", error1)
        seed_failed(registry, "my_app", "my_app_1", error2)

        snapshot = registry.get_snapshot()
        assert any(i.app_key == "my_app" and i.error is not None for i in snapshot.instances)
        failed = [f for f in snapshot.instances if f.error is not None and f.app_key == "my_app"]
        assert len(failed) == 2
        assert {f.instance_name for f in failed} == {"my_app", "my_app_1"}

    def test_failed_write_replaces_running_entry_under_same_name(
        self, registry: AppRegistry, mock_app: MagicMock
    ) -> None:
        """A FAILED write under a name with a running entry replaces it."""
        seed_running(registry, "my_app", mock_app)

        seed_failed(registry, "my_app", "my_app", ValueError("crashed"))

        assert registry.get("my_app", "my_app") is None
        assert "my_app" not in registry

    def test_second_failure_under_same_name_replaces_first(self, registry: AppRegistry) -> None:
        """Two failures recorded under the same name leave exactly one entry with the last error."""
        err1 = ValueError("first")
        err2 = ValueError("second")

        seed_failed(registry, "my_app", "my_app", err1)
        seed_failed(registry, "my_app", "my_app", err2)

        entries = registry.get_instances("my_app")

        assert len(entries) == 1
        assert entries["my_app"].error is err2

    def test_running_write_preserves_failure_under_other_name(self, registry: AppRegistry) -> None:
        """A running write under one name does not clear a failure recorded under a different name."""
        seed_failed(registry, "my_app", "my_app_2", ValueError("boom"))

        seed_running(registry, "my_app", MagicMock(instance_name="my_app"))

        entries = registry.get_instances("my_app")
        assert "my_app_2" in entries
        assert entries["my_app_2"].status == ResourceStatus.FAILED
        assert entries["my_app_2"].error_message == "boom"

    def test_get_live_apps_excludes_failed_entries(self, registry: AppRegistry) -> None:
        """get_live_apps() returns only running entries when failed entries exist for the
        same app_key.
        """
        app0 = MagicMock(instance_name="my_app")
        seed_running(registry, "my_app", app0)
        seed_failed(registry, "my_app", "my_app_1", ValueError("boom"))

        result = registry.get_live_apps("my_app")

        assert result == {"my_app": app0}

    def test_get_instances_returns_running_and_failed(self, registry: AppRegistry) -> None:
        """get_instances() returns all entries, running and failed."""
        app0 = MagicMock(instance_name="my_app")
        error = ValueError("boom")
        seed_running(registry, "my_app", app0)
        seed_failed(registry, "my_app", "my_app_1", error)

        entries = registry.get_instances("my_app")

        assert set(entries) == {"my_app", "my_app_1"}
        assert entries["my_app"].app is app0
        assert entries["my_app"].status == ResourceStatus.RUNNING
        assert entries["my_app_1"].app is None
        assert entries["my_app_1"].status == ResourceStatus.FAILED
        assert entries["my_app_1"].error is error

    def test_stale_failed_names_lists_failures_the_config_lacks(self, registry: AppRegistry) -> None:
        """A config shrink (3 instances -> 1) leaves failed entries under the now-removed names
        stranded in the registry unless something prunes them — create_instances() only
        ever touches names within the *current* config. The read changes nothing; the caller
        writes STOPPED for each name, so each removal sends its own event.
        """
        seed_failed(registry, "my_app", "a", ValueError("still fails"))
        seed_failed(registry, "my_app", "b", ValueError("stale - instance removed"))
        seed_failed(registry, "my_app", "c", ValueError("stale - instance removed"))

        stale = registry.stale_failed_names("my_app", ["a"])

        assert sorted(stale) == ["b", "c"]
        assert set(registry.get_instances("my_app")) == {"a", "b", "c"}

    def test_stale_failed_names_leaves_out_running_and_flagged_entries(self, registry: AppRegistry) -> None:
        """An orphaned running instance needs a real shutdown, and only clear_all removes a flagged entry."""
        seed_running(registry, "my_app", MagicMock(instance_name="a"))
        seed_failed(registry, "my_app", "b", ValueError("stale"))
        seed_failed(registry, "my_app", "c", ValueError("stale"), needs_restart="work still running")

        assert registry.stale_failed_names("my_app", []) == ["b"]

    def test_stale_failed_names_empty_for_unknown_app(self, registry: AppRegistry) -> None:
        """No entries for the app_key at all — an empty list, not an error."""
        assert registry.stale_failed_names("unknown_app", []) == []
        assert registry.get_instances("unknown_app") == {}

    def test_clear_failures_and_iter_all_instances_removed(self, registry: AppRegistry) -> None:
        """clear_failures() and iter_all_instances() no longer exist."""
        assert not hasattr(registry, "clear_failures")
        assert not hasattr(registry, "iter_all_instances")

    def test_get_existing_app(self, registry: AppRegistry, mock_app: MagicMock) -> None:
        """Test getting an existing app."""
        seed_running(registry, "my_app", mock_app)

        result = registry.get("my_app", "my_app")

        assert result is mock_app

    def test_get_nonexistent_app(self, registry: AppRegistry) -> None:
        """Test getting a nonexistent app."""
        result = registry.get("nonexistent", "nonexistent")
        assert result is None

    def test_get_without_a_name_returns_the_first_running_instance(
        self, registry: AppRegistry, mock_app: MagicMock
    ) -> None:
        """Test that get() without a name returns the first running instance."""
        seed_running(registry, "my_app", mock_app)

        result = registry.get("my_app")

        assert result is mock_app

    def test_all_apps(self, registry: AppRegistry) -> None:
        """Test getting all apps."""
        app1 = MagicMock(instance_name="app1")
        app2 = MagicMock(instance_name="app2")
        app3 = MagicMock(instance_name="app2_1")

        seed_running(registry, "app1", app1)
        seed_running(registry, "app2", app2)
        seed_running(registry, "app2", app3)

        all_apps = registry.all_apps()

        assert len(all_apps) == 3
        assert app1 in all_apps
        assert app2 in all_apps
        assert app3 in all_apps

    def test_get_live_apps(self, registry: AppRegistry, mock_app: MagicMock) -> None:
        """Test getting all running instances for a key."""
        app1 = MagicMock(instance_name="my_app")
        app2 = MagicMock(instance_name="my_app_1")
        seed_running(registry, "my_app", app1)
        seed_running(registry, "my_app", app2)

        result = registry.get_live_apps("my_app")

        assert result == {"my_app": app1, "my_app_1": app2}
        # Verify it's a copy
        result["extra"] = MagicMock()
        assert registry.get("my_app", "extra") is None

    def test_get_snapshot_empty(self, registry: AppRegistry) -> None:
        """Test snapshot with no apps."""
        snapshot = registry.get_snapshot()

        assert snapshot.instances == ()
        assert snapshot.only_apps == ()

    def test_get_snapshot_with_running_apps(self, registry: AppRegistry, mock_app: MagicMock) -> None:
        """Test snapshot includes running apps."""
        mock_app.status = ResourceStatus.RUNNING
        mock_app.instance_name = "test_instance"
        mock_app.app_config.instance_name = "test_instance"
        seed_running(registry, "my_app", mock_app)

        snapshot = registry.get_snapshot()

        running = [i for i in snapshot.instances if i.error is None]
        assert len(running) == 1
        info = running[0]
        assert info.app_key == "my_app"
        assert info.instance_name == "test_instance"
        assert info.class_name == "TestApp"
        assert info.status == ResourceStatus.RUNNING

    def test_get_snapshot_with_failed_apps(self, registry: AppRegistry, mock_manifest: MagicMock) -> None:
        """Test snapshot includes failed apps."""
        error = Exception("startup failed")
        registry.set_manifests({"my_app": mock_manifest})
        seed_failed(registry, "my_app", "test_instance", error)

        snapshot = registry.get_snapshot()

        failed = [i for i in snapshot.instances if i.error is not None]
        assert len(failed) == 1
        info = failed[0]
        assert info.app_key == "my_app"
        assert info.status == ResourceStatus.FAILED
        assert info.error is error
        assert info.error_message == "startup failed"

    def test_get_snapshot_two_running_and_one_failed(self, registry: AppRegistry) -> None:
        """Characterization pin: 2 running instances + 1 failure produce a snapshot with
        a single `.instances` list containing correct per-entry field values.
        """
        app1 = MagicMock(instance_name="app1")
        app1.app_config.instance_name = "app1"
        app1.class_name = "App1"
        app1.status = ResourceStatus.RUNNING
        app1.unique_name = "app1"

        app2 = MagicMock(instance_name="app2")
        app2.app_config.instance_name = "app2"
        app2.class_name = "App2"
        app2.status = ResourceStatus.RUNNING
        app2.unique_name = "app2"

        seed_running(registry, "app1", app1)
        seed_running(registry, "app2", app2)

        error = ValueError("boom")
        seed_failed(registry, "app3", "app3", error)

        snapshot = registry.get_snapshot()

        running = [i for i in snapshot.instances if i.error is None]
        failed = [i for i in snapshot.instances if i.error is not None]
        assert len(running) == 2
        assert len(failed) == 1

        running_by_key = {info.app_key: info for info in running}
        assert running_by_key["app1"].instance_name == "app1"
        assert running_by_key["app1"].class_name == "App1"
        assert running_by_key["app1"].status == ResourceStatus.RUNNING
        assert running_by_key["app1"].owner_id == "app1"
        assert running_by_key["app2"].app_key == "app2"
        assert running_by_key["app2"].class_name == "App2"

        failed_info = failed[0]
        assert failed_info.app_key == "app3"
        assert failed_info.status == ResourceStatus.FAILED
        assert failed_info.error is error
        assert failed_info.error_message == "boom"

    def test_get_snapshot_with_only_apps(self, registry: AppRegistry) -> None:
        """Test snapshot includes only_apps, sorted for stable output."""
        registry.set_only_apps(["special_app", "other_app"])

        snapshot = registry.get_snapshot()

        assert snapshot.only_apps == ("other_app", "special_app")

    def test_get_snapshot_reports_the_entry_status_not_the_app_status(self, registry: AppRegistry) -> None:
        """A live instance's snapshot status is the registry entry's, whatever the App resource says (D4)."""
        app = MagicMock()
        app.instance_name = "app"
        app.class_name = "Test"
        app.status = ResourceStatus.RUNNING
        seed_running(registry, "app", app, status=ResourceStatus.STARTING)

        snapshot = registry.get_snapshot()

        assert snapshot.instances[0].status == ResourceStatus.STARTING

    def test_clear_all(self, registry: AppRegistry, mock_app: MagicMock) -> None:
        """Test clearing all apps and failures."""
        seed_running(registry, "app1", mock_app)
        seed_failed(registry, "app2", "app2", Exception("error"))

        registry.clear_all()

        assert len(registry.app_keys()) == 0
        assert registry.get_snapshot().failed_count == 0

    def test_set_manifests(self, registry: AppRegistry, mock_manifest: MagicMock) -> None:
        """Test setting manifests."""
        manifests: dict[str, AppManifest] = {"app1": mock_manifest}
        registry.set_manifests(manifests)

        assert registry.manifests == manifests
        # Verify it's a copy
        manifests["app2"] = MagicMock()
        assert "app2" not in registry.manifests

    def test_set_only_apps(self, registry: AppRegistry) -> None:
        """Test setting and clearing the exclusive-app filter."""
        registry.set_only_apps(["my_app", "other_app"])
        assert registry.only_apps == frozenset({"my_app", "other_app"})

        registry.set_only_apps(())
        assert registry.only_apps == frozenset()

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

    def test_active_manifests_narrows_to_only_apps(self, registry: AppRegistry) -> None:
        """active_manifests keeps every key in the filter and drops the rest."""
        manifests = {}
        for key in ("app1", "app2", "app3"):
            manifest = MagicMock()
            manifest.enabled = True
            manifests[key] = manifest
        registry.set_manifests(manifests)
        registry.set_only_apps(["app1", "app3"])

        assert set(registry.active_manifests) == {"app1", "app3"}

    def test_active_manifests_unfiltered_when_only_apps_empty(self, registry: AppRegistry) -> None:
        """An empty filter means every enabled app is active."""
        manifest = MagicMock()
        manifest.enabled = True
        registry.set_manifests({"app1": manifest, "app2": manifest})

        assert set(registry.active_manifests) == {"app1", "app2"}
