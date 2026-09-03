"""Tests for AppChangeDetector."""

from collections.abc import Callable
from pathlib import Path

import pytest

from hassette.config.classes import AppManifest
from hassette.core.app_change_detector import (
    APP_CONFIG_PATH_PATTERN,
    REIMPORT_PATH_PATTERN,
    AppChangeDetector,
    ChangeSet,
)


class TestAppConfigPathPattern:
    """APP_CONFIG_PATH_PATTERN must match `.app_config` as a full path segment, not as a
    substring of a longer field name — the same substring-matching pitfall documented on
    `AppChangeDetector`'s `include_paths` handling (see the comment there on why DeepDiff's
    `include_paths` can't express "only descend into this specific nested field").
    """

    @pytest.mark.parametrize(
        "path",
        [
            "root['app1'].app_config",
            "root['app1'].app_config['setting']",
            "root['app1'].app_config[0]",
        ],
    )
    def test_matches_app_config_segment(self, path: str) -> None:
        assert APP_CONFIG_PATH_PATTERN.search(path)

    @pytest.mark.parametrize(
        "path",
        [
            "root['app1'].app_config_extra",
            "root['app1'].app_config_version",
            "root['app1'].legacy_app_config",
        ],
    )
    def test_does_not_match_field_name_prefix_collision(self, path: str) -> None:
        assert not APP_CONFIG_PATH_PATTERN.search(path)


class TestReimportPathPattern:
    """REIMPORT_PATH_PATTERN must match `.filename`/`.class_name`/`.app_dir`/`.cache_key` as
    full path segments, not as a substring of a longer field name (e.g. a future
    `filename_prefix` field must not match) -- same substring-safety concern as
    `APP_CONFIG_PATH_PATTERN`.
    """

    @pytest.mark.parametrize(
        "path",
        [
            "root['app1'].filename",
            "root['app1'].class_name",
            "root['app1'].app_dir",
            "root['app1'].cache_key",
        ],
    )
    def test_matches_reimport_field_segment(self, path: str) -> None:
        assert REIMPORT_PATH_PATTERN.search(path)

    @pytest.mark.parametrize(
        "path",
        [
            "root['app1'].filename_prefix",
            "root['app1'].class_name_override",
            "root['app1'].app_config",
            "root['app1'].app_dir_override",
            "root['app1'].cache_key_override",
        ],
    )
    def test_does_not_match_field_name_prefix_collision(self, path: str) -> None:
        assert not REIMPORT_PATH_PATTERN.search(path)


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
            changes.orphans = frozenset({"b"})  # pyright: ignore[reportCallIssue]


class TestAppChangeDetector:
    @pytest.fixture
    def detector(self) -> AppChangeDetector:
        return AppChangeDetector()

    @pytest.fixture
    def make_manifest(self) -> Callable:  # factory-local: needs display_name/autostart overrides not in
        # tests/support/helpers.py's create_app_manifest, and real (non-Mock) instances are required here --
        # DeepDiff cannot do attribute-level diffing on MagicMock objects (MagicMock auto-configures magic
        # methods like __iter__, which makes DeepDiff treat two mock instances as opaque and report a
        # whole-object type_changes entry instead of diffing individual attributes), so field-level
        # detection (display_name vs. app_config) can't be exercised with mocks.
        """Factory for creating real AppManifest instances."""

        def _make(
            app_key: str,
            full_path: Path | None = None,
            app_config: dict | None = None,
            display_name: str | None = None,
            autostart: bool = True,
            filename: str | None = None,
            class_name: str | None = None,
            app_dir: Path | None = None,
            cache_key: str | None = None,
        ) -> AppManifest:
            return AppManifest(
                app_key=app_key,
                filename=filename or f"{app_key}.py",
                class_name=class_name or app_key.capitalize(),
                display_name=display_name or app_key,
                app_dir=app_dir or Path("/apps"),
                app_config=app_config or {"instance_name": f"{app_key}.0"},
                full_path=full_path or Path(f"/apps/{app_key}.py"),
                autostart=autostart,
                cache_key=cache_key or "",
            )

        return _make

    def test_no_changes(self, detector: AppChangeDetector, make_manifest: Callable) -> None:
        """Test detecting no changes."""
        config = {"app1": make_manifest("app1")}

        changes = detector.detect_changes(config, config)

        assert not changes.has_changes

    def test_detect_orphans(self, detector: AppChangeDetector, make_manifest: Callable) -> None:
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

    def test_detect_new_apps(self, detector: AppChangeDetector, make_manifest: Callable) -> None:
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

    def test_detect_reimport_apps(self, detector: AppChangeDetector, make_manifest: Callable) -> None:
        """Test detecting apps needing reimport due to file change."""
        changed_path = Path("/apps/app1.py")
        original = {"app1": make_manifest("app1", full_path=changed_path)}
        current = {"app1": make_manifest("app1", full_path=changed_path)}

        changes = detector.detect_changes(original, current, changed_file_paths=frozenset({changed_path}))

        assert changes.reimport_apps == frozenset({"app1"})
        assert not changes.orphans
        assert not changes.new_apps
        assert not changes.reload_apps

    def test_detect_reload_apps(self, detector: AppChangeDetector, make_manifest: Callable) -> None:
        """Test detecting apps needing reload due to config change."""
        original = {"app1": make_manifest("app1", app_config={"instance_name": "app1.0", "setting": "old"})}
        current = {"app1": make_manifest("app1", app_config={"instance_name": "app1.0", "setting": "new"})}

        changes = detector.detect_changes(original, current)

        assert changes.reload_apps == frozenset({"app1"})
        assert not changes.orphans
        assert not changes.new_apps
        assert not changes.reimport_apps

    def test_display_name_change_does_not_trigger_reload(
        self, detector: AppChangeDetector, make_manifest: Callable
    ) -> None:
        """A display_name-only change is not an app_config change and must not trigger a reload."""
        original = {"app1": make_manifest("app1", display_name="Old Name")}
        current = {"app1": make_manifest("app1", display_name="New Name")}

        changes = detector.detect_changes(original, current)

        assert "app1" not in changes.reload_apps
        assert not changes.has_changes

    def test_autostart_change_does_not_trigger_reload(
        self, detector: AppChangeDetector, make_manifest: Callable
    ) -> None:
        """An autostart-only change is not an app_config change and must not trigger a reload."""
        original = {"app1": make_manifest("app1", autostart=True)}
        current = {"app1": make_manifest("app1", autostart=False)}

        changes = detector.detect_changes(original, current)

        assert "app1" not in changes.reload_apps
        assert not changes.has_changes

    def test_app_config_change_triggers_reload(self, detector: AppChangeDetector, make_manifest: Callable) -> None:
        """An app_config change must still trigger a reload, even alongside a non-config change."""
        original = {
            "app1": make_manifest("app1", app_config={"setting": "old"}, display_name="Same Name"),
        }
        current = {
            "app1": make_manifest("app1", app_config={"setting": "new"}, display_name="Same Name"),
        }

        changes = detector.detect_changes(original, current)

        assert changes.reload_apps == frozenset({"app1"})

    def test_new_app_not_in_reload(self, detector: AppChangeDetector, make_manifest: Callable) -> None:
        """Test that new apps are not also in reload_apps."""
        original: dict = {}
        current = {"app1": make_manifest("app1")}

        changes = detector.detect_changes(original, current)

        assert "app1" in changes.new_apps
        assert "app1" not in changes.reload_apps

    def test_reimport_not_in_reload(self, detector: AppChangeDetector, make_manifest: Callable) -> None:
        """Test that reimport apps are not also in reload_apps."""
        changed_path = Path("/apps/app1.py")
        # Config change + file change should only be reimport
        original = {"app1": make_manifest("app1", full_path=changed_path, app_config={"setting": "old"})}
        current = {"app1": make_manifest("app1", full_path=changed_path, app_config={"setting": "new"})}

        changes = detector.detect_changes(original, current, changed_file_paths=frozenset({changed_path}))

        assert "app1" in changes.reimport_apps
        assert "app1" not in changes.reload_apps

    def test_only_apps_parameter_excludes_other_apps(
        self, detector: AppChangeDetector, make_manifest: Callable
    ) -> None:
        """Passing only_apps to detect_changes excludes other apps from current."""
        original = {"app1": make_manifest("app1"), "app2": make_manifest("app2")}
        current = {"app1": make_manifest("app1"), "app2": make_manifest("app2")}

        changes = detector.detect_changes(original, current, only_apps=frozenset({"app1"}))

        # app2 should be seen as orphan since it's filtered out of current
        assert "app2" in changes.orphans

    def test_only_apps_parameter_allows_target_apps(self, detector: AppChangeDetector, make_manifest: Callable) -> None:
        """Passing only_apps to detect_changes allows every named app through the filter."""
        original: dict = {}
        current = {
            "app1": make_manifest("app1"),
            "app2": make_manifest("app2"),
            "app3": make_manifest("app3"),
        }

        changes = detector.detect_changes(original, current, only_apps=frozenset({"app1", "app2"}))

        assert changes.new_apps == frozenset({"app1", "app2"})

    def test_only_apps_none_allows_all_apps(self, detector: AppChangeDetector, make_manifest: Callable) -> None:
        """Passing only_apps=None (the default) applies no filter."""
        original: dict = {}
        current = {"app1": make_manifest("app1"), "app2": make_manifest("app2")}

        changes = detector.detect_changes(original, current, only_apps=None)

        assert "app1" in changes.new_apps
        assert "app2" in changes.new_apps

    def test_detector_holds_no_only_apps_state(self) -> None:
        """AppChangeDetector has no only_app_filter instance field or set_only_app_filter method."""
        detector = AppChangeDetector()
        assert not hasattr(detector, "only_app_filter"), "only_app_filter field must not exist"
        assert not hasattr(detector, "set_only_app_filter"), "set_only_app_filter method must not exist"

    def test_new_app_with_file_change_not_in_reimport(
        self, detector: AppChangeDetector, make_manifest: Callable
    ) -> None:
        """A brand-new app whose file also changed should only be in new_apps, not reimport."""
        new_path = Path("/apps/new_app.py")
        original: dict = {}
        current = {"new_app": make_manifest("new_app", full_path=new_path)}

        changes = detector.detect_changes(original, current, changed_file_paths=frozenset({new_path}))

        assert "new_app" in changes.new_apps
        assert "new_app" not in changes.reimport_apps

    def test_only_apps_parameter_excludes_reimport_for_non_target(
        self, detector: AppChangeDetector, make_manifest: Callable
    ) -> None:
        """Apps filtered out by only_apps should not appear in reimport_apps."""
        changed_path_1 = Path("/apps/app1.py")
        changed_path_2 = Path("/apps/app2.py")

        original = {
            "app1": make_manifest("app1", full_path=changed_path_1),
            "app2": make_manifest("app2", full_path=changed_path_2),
        }
        current = {
            "app1": make_manifest("app1", full_path=changed_path_1),
            "app2": make_manifest("app2", full_path=changed_path_2),
        }

        changes = detector.detect_changes(
            original,
            current,
            changed_file_paths=frozenset({changed_path_1, changed_path_2}),
            only_apps=frozenset({"app1"}),
        )

        assert "app1" in changes.reimport_apps
        assert "app2" not in changes.reimport_apps
        assert "app2" in changes.orphans

    def test_multiple_changes(self, detector: AppChangeDetector, make_manifest: Callable) -> None:
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

        changes = detector.detect_changes(original, current, changed_file_paths=frozenset({changed_path}))

        assert changes.orphans == frozenset({"app1"})
        assert changes.new_apps == frozenset({"app4"})
        assert changes.reimport_apps == frozenset({"app2"})
        assert changes.reload_apps == frozenset({"app3"})

    def test_only_apps_excludes_reload_for_non_target(
        self, detector: AppChangeDetector, make_manifest: Callable
    ) -> None:
        """Config changes on apps filtered out by only_apps must not appear in reload_apps."""
        original = {
            "app1": make_manifest("app1", app_config={"setting": "old"}),
            "app2": make_manifest("app2", app_config={"setting": "old"}),
            "app3": make_manifest("app3", app_config={"setting": "old"}),
        }
        current = {
            "app1": make_manifest("app1", app_config={"setting": "new"}),
            "app2": make_manifest("app2", app_config={"setting": "new"}),
            "app3": make_manifest("app3", app_config={"setting": "new"}),
        }

        changes = detector.detect_changes(original, current, only_apps=frozenset({"app1"}))

        assert "app1" in changes.reload_apps
        assert "app2" not in changes.reload_apps
        assert "app3" not in changes.reload_apps

    def test_filename_change_triggers_reimport_not_reload(
        self, detector: AppChangeDetector, make_manifest: Callable
    ) -> None:
        """A filename-only change (no app_config change, no file-watcher event) must land in
        reimport_apps -- not reload_apps -- so apply_changes() forces a class reimport instead
        of a config-only reload. See app_change_detector.py:106 comment.
        """
        original = {"app1": make_manifest("app1", filename="old_app1.py")}
        current = {"app1": make_manifest("app1", filename="new_app1.py")}

        changes = detector.detect_changes(original, current)

        assert changes.reimport_apps == frozenset({"app1"})
        assert "app1" not in changes.reload_apps
        assert not changes.orphans
        assert not changes.new_apps

    def test_class_name_change_triggers_reimport_not_reload(
        self, detector: AppChangeDetector, make_manifest: Callable
    ) -> None:
        """A class_name-only change must also land in reimport_apps, not reload_apps."""
        original = {"app1": make_manifest("app1", class_name="OldApp")}
        current = {"app1": make_manifest("app1", class_name="NewApp")}

        changes = detector.detect_changes(original, current)

        assert changes.reimport_apps == frozenset({"app1"})
        assert "app1" not in changes.reload_apps

    def test_app_dir_change_triggers_reimport_not_reload(
        self, detector: AppChangeDetector, make_manifest: Callable
    ) -> None:
        """An app_dir-only change must also land in reimport_apps, not reload_apps.

        full_path (the file the app actually loads from) is app_dir / filename, so moving
        an app to a new directory changes its implementation target just as surely as
        renaming its file -- and is just as invisible to the file watcher (which reports
        the changed *configuration* file, not the app's new source path).
        """
        original = {"app1": make_manifest("app1", app_dir=Path("/apps/old"))}
        current = {"app1": make_manifest("app1", app_dir=Path("/apps/new"))}

        changes = detector.detect_changes(original, current)

        assert changes.reimport_apps == frozenset({"app1"})
        assert "app1" not in changes.reload_apps

    def test_cache_key_change_triggers_reimport_not_reload(
        self, detector: AppChangeDetector, make_manifest: Callable
    ) -> None:
        """A cache_key-only change (no app_config change, no file-watcher event) must land in
        reimport_apps -- not reload_apps. App.__init__ builds its AsyncCache exactly once,
        keyed on the manifest's cache_key at construction time; reload_apps's per-instance path
        only diffs app_config, so a cache_key-only change would otherwise silently no-op and
        leave the running instance bound to its old cache path. See
        app_change_detector.py's REIMPORT_FIELDS docstring.
        """
        original = {"app1": make_manifest("app1", cache_key="old_key")}
        current = {"app1": make_manifest("app1", cache_key="new_key")}

        changes = detector.detect_changes(original, current)

        assert changes.reimport_apps == frozenset({"app1"})
        assert "app1" not in changes.reload_apps
        assert not changes.orphans
        assert not changes.new_apps

    def test_filename_and_app_config_change_together_only_in_reimport(
        self, detector: AppChangeDetector, make_manifest: Callable
    ) -> None:
        """When app_config and filename change together for the same app_key, the app must end
        up in exactly one bucket -- reimport_apps -- since force_reload implies a fresh config
        load too. It must not also appear in reload_apps.
        """
        original = {
            "app1": make_manifest("app1", filename="old_app1.py", app_config={"setting": "old"}),
        }
        current = {
            "app1": make_manifest("app1", filename="new_app1.py", app_config={"setting": "new"}),
        }

        changes = detector.detect_changes(original, current)

        assert changes.reimport_apps == frozenset({"app1"})
        assert "app1" not in changes.reload_apps

    def test_app_config_only_change_unaffected_by_implementation_detection(
        self, detector: AppChangeDetector, make_manifest: Callable
    ) -> None:
        """Regression check: an app_config-only change (no filename/class_name change) must
        still route to reload_apps, not reimport_apps, now that implementation-field detection
        exists alongside it.
        """
        original = {"app1": make_manifest("app1", app_config={"setting": "old"})}
        current = {"app1": make_manifest("app1", app_config={"setting": "new"})}

        changes = detector.detect_changes(original, current)

        assert changes.reload_apps == frozenset({"app1"})
        assert "app1" not in changes.reimport_apps
