"""Tests for AppChangeDetector."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hassette.core.app_change_detector import AppChangeDetector, ChangeSet


class TestChangeSet:
    def test_empty_changeset(self) -> None:
        """Test empty changeset."""
        changes = ChangeSet(
            orphans=frozenset(),
            new_apps=frozenset(),
            reimport_apps=frozenset(),
            reload_apps=frozenset(),
        )

        assert not changes.has_changes
        assert changes.orphans == frozenset()
        assert changes.new_apps == frozenset()
        assert changes.reimport_apps == frozenset()
        assert changes.reload_apps == frozenset()

    def test_has_changes_with_orphans(self) -> None:
        """Test has_changes is True when there are orphans."""
        changes = ChangeSet(
            orphans=frozenset({"app1"}),
            new_apps=frozenset(),
            reimport_apps=frozenset(),
            reload_apps=frozenset(),
        )
        assert changes.has_changes

    def test_has_changes_with_new_apps(self) -> None:
        """Test has_changes is True when there are new apps."""
        changes = ChangeSet(
            orphans=frozenset(),
            new_apps=frozenset({"app1"}),
            reimport_apps=frozenset(),
            reload_apps=frozenset(),
        )
        assert changes.has_changes

    def test_has_changes_with_reimport_apps(self) -> None:
        """Test has_changes is True when there are reimport apps."""
        changes = ChangeSet(
            orphans=frozenset(),
            new_apps=frozenset(),
            reimport_apps=frozenset({"app1"}),
            reload_apps=frozenset(),
        )
        assert changes.has_changes

    def test_has_changes_with_reload_apps(self) -> None:
        """Test has_changes is True when there are reload apps."""
        changes = ChangeSet(
            orphans=frozenset(),
            new_apps=frozenset(),
            reimport_apps=frozenset(),
            reload_apps=frozenset({"app1"}),
        )
        assert changes.has_changes

    def test_repr(self) -> None:
        """Test string representation."""
        changes = ChangeSet(
            orphans=frozenset({"a"}),
            new_apps=frozenset({"b"}),
            reimport_apps=frozenset({"c"}),
            reload_apps=frozenset({"d"}),
        )
        repr_str = repr(changes)

        assert "orphans" in repr_str
        assert "new" in repr_str
        assert "reimport" in repr_str
        assert "reload" in repr_str

    def test_immutability(self) -> None:
        """Test that ChangeSet is immutable (frozen)."""
        changes = ChangeSet(
            orphans=frozenset({"a"}),
            new_apps=frozenset(),
            reimport_apps=frozenset(),
            reload_apps=frozenset(),
        )

        with pytest.raises(AttributeError):
            changes.orphans = frozenset({"b"})  # type: ignore[misc]


class TestAppChangeDetector:
    @pytest.fixture
    def detector(self) -> AppChangeDetector:
        return AppChangeDetector()

    @pytest.fixture
    def make_manifest(self) -> callable:
        """Factory for creating mock manifests."""

        def _make(app_key: str, full_path: Path | None = None, app_config: dict | None = None) -> MagicMock:
            manifest = MagicMock()
            manifest.app_key = app_key
            manifest.full_path = full_path or Path(f"/apps/{app_key}.py")
            manifest.app_config = app_config or {"instance_name": f"{app_key}.0"}
            return manifest

        return _make

    # --- Basic detection tests ---

    def test_no_changes(self, detector: AppChangeDetector, make_manifest: callable) -> None:
        """Test detecting no changes."""
        config = {"app1": make_manifest("app1")}

        changes = detector.detect_changes(config, config)

        assert not changes.has_changes

    def test_detect_orphans(self, detector: AppChangeDetector, make_manifest: callable) -> None:
        """Test detecting removed apps (orphans)."""
        app1_manifest = make_manifest("app1")
        app2_manifest = make_manifest("app2")

        original = {"app1": app1_manifest, "app2": app2_manifest}
        current = {"app1": app1_manifest}  # Reuse same manifest

        changes = detector.detect_changes(original, current)

        assert changes.orphans == frozenset({"app2"})
        assert not changes.new_apps
        assert not changes.reimport_apps
        assert not changes.reload_apps

    def test_detect_new_apps(self, detector: AppChangeDetector, make_manifest: callable) -> None:
        """Test detecting new apps."""
        app1_manifest = make_manifest("app1")
        app2_manifest = make_manifest("app2")

        original = {"app1": app1_manifest}
        current = {"app1": app1_manifest, "app2": app2_manifest}  # Reuse same manifest

        changes = detector.detect_changes(original, current)

        assert changes.new_apps == frozenset({"app2"})
        assert not changes.orphans
        assert not changes.reimport_apps
        assert not changes.reload_apps

    def test_detect_reimport_apps(self, detector: AppChangeDetector, make_manifest: callable) -> None:
        """Test detecting apps needing reimport due to file change."""
        changed_path = Path("/apps/app1.py")
        original = {"app1": make_manifest("app1", full_path=changed_path)}
        current = {"app1": make_manifest("app1", full_path=changed_path)}

        changes = detector.detect_changes(original, current, changed_file_path=changed_path)

        assert changes.reimport_apps == frozenset({"app1"})
        assert not changes.orphans
        assert not changes.new_apps
        assert not changes.reload_apps

    def test_detect_reload_apps(self, detector: AppChangeDetector, make_manifest: callable) -> None:
        """Test detecting apps needing reload due to config change."""
        original = {"app1": make_manifest("app1", app_config={"instance_name": "app1.0", "setting": "old"})}
        current = {"app1": make_manifest("app1", app_config={"instance_name": "app1.0", "setting": "new"})}

        changes = detector.detect_changes(original, current)

        assert changes.reload_apps == frozenset({"app1"})
        assert not changes.orphans
        assert not changes.new_apps
        assert not changes.reimport_apps

    # --- Priority tests ---

    def test_new_app_not_in_reload(self, detector: AppChangeDetector, make_manifest: callable) -> None:
        """Test that new apps are not also in reload_apps."""
        original: dict = {}
        current = {"app1": make_manifest("app1")}

        changes = detector.detect_changes(original, current)

        assert "app1" in changes.new_apps
        assert "app1" not in changes.reload_apps

    def test_reimport_not_in_reload(self, detector: AppChangeDetector, make_manifest: callable) -> None:
        """Test that reimport apps are not also in reload_apps."""
        changed_path = Path("/apps/app1.py")
        # Config change + file change should only be reimport
        original = {"app1": make_manifest("app1", full_path=changed_path, app_config={"setting": "old"})}
        current = {"app1": make_manifest("app1", full_path=changed_path, app_config={"setting": "new"})}

        changes = detector.detect_changes(original, current, changed_file_path=changed_path)

        assert "app1" in changes.reimport_apps
        assert "app1" not in changes.reload_apps

    # --- Only app filter tests ---

    def test_only_app_filter_excludes_other_apps(self, detector: AppChangeDetector, make_manifest: callable) -> None:
        """Test that only_app filter excludes other apps from current."""
        detector.set_only_app_filter("app1")

        original = {"app1": make_manifest("app1"), "app2": make_manifest("app2")}
        current = {"app1": make_manifest("app1"), "app2": make_manifest("app2")}

        changes = detector.detect_changes(original, current)

        # app2 should be seen as orphan since it's filtered out of current
        assert "app2" in changes.orphans

    def test_only_app_filter_allows_target_app(self, detector: AppChangeDetector, make_manifest: callable) -> None:
        """Test that only_app filter allows the target app."""
        detector.set_only_app_filter("app1")

        original: dict = {}
        current = {"app1": make_manifest("app1"), "app2": make_manifest("app2")}

        changes = detector.detect_changes(original, current)

        assert "app1" in changes.new_apps
        assert "app2" not in changes.new_apps

    def test_set_only_app_filter(self, detector: AppChangeDetector) -> None:
        """Test setting the only_app filter."""
        assert detector.only_app_filter is None

        detector.set_only_app_filter("my_app")
        assert detector.only_app_filter == "my_app"

        detector.set_only_app_filter(None)
        assert detector.only_app_filter is None

    def test_init_with_only_app_filter(self) -> None:
        """Test creating detector with initial only_app filter."""
        detector = AppChangeDetector(only_app_filter="my_app")
        assert detector.only_app_filter == "my_app"

    # --- Complex scenarios ---

    def test_multiple_changes(self, detector: AppChangeDetector, make_manifest: callable) -> None:
        """Test detecting multiple types of changes at once."""
        changed_path = Path("/apps/app2.py")

        original = {
            "app1": make_manifest("app1"),  # will be orphaned
            "app2": make_manifest("app2", full_path=changed_path),  # will be reimported
            "app3": make_manifest("app3", app_config={"setting": "old"}),  # will be reloaded
        }
        current = {
            # app1 removed
            "app2": make_manifest("app2", full_path=changed_path),  # file changed
            "app3": make_manifest("app3", app_config={"setting": "new"}),  # config changed
            "app4": make_manifest("app4"),  # new app
        }

        changes = detector.detect_changes(original, current, changed_file_path=changed_path)

        assert changes.orphans == frozenset({"app1"})
        assert changes.new_apps == frozenset({"app4"})
        assert changes.reimport_apps == frozenset({"app2"})
        assert changes.reload_apps == frozenset({"app3"})
