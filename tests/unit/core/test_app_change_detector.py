"""Tests for AppChangeDetector."""

from collections.abc import Callable
from pathlib import Path

import pytest

from hassette.config.classes import AppManifest
from hassette.core.app_change_detector import (
    APP_CONFIG_PATH_PATTERN,
    REIMPORT_PATH_PATTERN,
    AppChangeDetector,
)
from tests.support.factories import make_change_set


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
        changes = make_change_set()

        assert not changes.has_changes
        assert not changes.has_any_change
        assert changes.orphans == frozenset()
        assert changes.new_apps == frozenset()
        assert changes.reimport_apps == frozenset()
        assert changes.reload_apps == frozenset()
        assert changes.metadata_apps == frozenset()

    def test_has_any_change_true_with_metadata_apps_only(self) -> None:
        """has_any_change is True on a metadata-only changeset even though has_changes is False --
        this is the distinction the broadcast-on-metadata-only-change fix relies on.
        """
        changes = make_change_set(metadata_apps={"app1"})

        assert not changes.has_changes
        assert changes.has_any_change

    def test_has_changes_with_orphans(self) -> None:
        """Test has_changes is True when there are orphans."""
        changes = make_change_set(orphans={"app1"})
        assert changes.has_changes

    def test_has_changes_with_new_apps(self) -> None:
        """Test has_changes is True when there are new apps."""
        changes = make_change_set(new_apps={"app1"})
        assert changes.has_changes

    def test_has_changes_with_reimport_apps(self) -> None:
        """Test has_changes is True when there are reimport apps."""
        changes = make_change_set(reimport_apps={"app1"})
        assert changes.has_changes

    def test_has_changes_with_reload_apps(self) -> None:
        """Test has_changes is True when there are reload apps."""
        changes = make_change_set(reload_apps={"app1"})
        assert changes.has_changes

    def test_repr(self) -> None:
        """Test string representation."""
        changes = make_change_set(orphans={"a"}, new_apps={"b"}, reimport_apps={"c"}, reload_apps={"d"})
        repr_str = repr(changes)

        assert "orphans" in repr_str
        assert "new" in repr_str
        assert "reimport" in repr_str
        assert "reload" in repr_str

    def test_immutability(self) -> None:
        """Test that ChangeSet is immutable (frozen)."""
        changes = make_change_set(orphans={"a"})

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
            enabled: bool = True,
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
                enabled=enabled,
            )

        return _make

    def test_no_changes(self, detector: AppChangeDetector, make_manifest: Callable) -> None:
        """Test detecting no changes."""
        config = {"app1": make_manifest("app1")}

        changes = detector.detect_changes(config, config)

        assert not changes.has_changes
        assert not changes.has_any_change
        assert not changes.metadata_apps

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

    @pytest.mark.parametrize(
        ("original_config", "current_config"),
        [
            (None, None),
            ({"setting": "old"}, {"setting": "new"}),
        ],
        ids=["config_unchanged", "config_also_changed"],
    )
    def test_changed_file_path_triggers_reimport_not_reload(
        self,
        detector: AppChangeDetector,
        make_manifest: Callable,
        original_config: dict | None,
        current_config: dict | None,
    ) -> None:
        """A file-watcher event for an app's source file routes that app to reimport_apps, and
        keeps it out of reload_apps even when its app_config changed in the same pass -- a forced
        reimport reloads config too, so a reload entry would be redundant.
        """
        changed_path = Path("/apps/app1.py")
        original = {"app1": make_manifest("app1", full_path=changed_path, app_config=original_config)}
        current = {"app1": make_manifest("app1", full_path=changed_path, app_config=current_config)}

        changes = detector.detect_changes(original, current, changed_file_paths=frozenset({changed_path}))

        assert changes.reimport_apps == frozenset({"app1"})
        assert "app1" not in changes.reload_apps
        assert not changes.orphans
        assert not changes.new_apps

    @pytest.mark.parametrize(
        ("companion_original", "companion_current"),
        [
            ({}, {}),
            ({"display_name": "Same Name"}, {"display_name": "Same Name"}),
            ({"display_name": "Old Name"}, {"display_name": "New Name"}),
        ],
        ids=["config_only", "display_name_unchanged", "display_name_also_changed"],
    )
    def test_app_config_change_routes_to_reload_only(
        self,
        detector: AppChangeDetector,
        make_manifest: Callable,
        companion_original: dict,
        companion_current: dict,
    ) -> None:
        """An app_config change routes to reload_apps and to nothing else.

        It stays in reload_apps whether or not a non-config attribute changes alongside it, is
        not re-routed to reimport_apps by the implementation-field detection that runs in the
        same pass, and never also appears in metadata_apps -- which does not double-count an app
        already claimed by a lifecycle category.
        """
        original = {"app1": make_manifest("app1", app_config={"setting": "old"}, **companion_original)}
        current = {"app1": make_manifest("app1", app_config={"setting": "new"}, **companion_current)}

        changes = detector.detect_changes(original, current)

        assert changes.reload_apps == frozenset({"app1"})
        assert not changes.orphans
        assert not changes.new_apps
        assert not changes.reimport_apps
        assert "app1" not in changes.metadata_apps

    @pytest.mark.parametrize(
        ("original_kwargs", "current_kwargs", "detect_kwargs"),
        [
            ({"display_name": "Old Name"}, {"display_name": "New Name"}, {}),
            ({"autostart": True}, {"autostart": False}, {}),
            (
                {"display_name": "Old Name", "enabled": False},
                {"display_name": "New Name", "enabled": False},
                {},
            ),
            (
                {"display_name": "Old Name", "enabled": False},
                {"display_name": "New Name", "enabled": False},
                {"only_apps": frozenset({"app2"})},
            ),
        ],
        ids=["display_name", "autostart", "disabled_app", "excluded_by_only_apps"],
    )
    def test_non_lifecycle_change_surfaces_as_metadata_only(
        self,
        detector: AppChangeDetector,
        make_manifest: Callable,
        original_kwargs: dict,
        current_kwargs: dict,
        detect_kwargs: dict,
    ) -> None:
        """A manifest change that is neither an app_config change nor an implementation-target
        change requires no lifecycle action, but must still surface in metadata_apps so a
        connected dashboard is told to refetch (see test_app_lifecycle_service_coverage.py's
        metadata-broadcast tests).

        This holds for an app disabled on both sides -- detect_changes() is deliberately handed
        every manifest rather than an enabled-only pre-filtered pair, so a disabled app's
        metadata changes stay visible (see PR #1899 review) -- and for an app that `only_apps`
        excludes, since `only_apps` narrows which apps get lifecycle actions, not which manifest
        changes are worth telling a dashboard about.
        """
        original = {"app1": make_manifest("app1", **original_kwargs)}
        current = {"app1": make_manifest("app1", **current_kwargs)}

        changes = detector.detect_changes(original, current, **detect_kwargs)

        # has_changes is the disjunction of the four lifecycle buckets, so this single assertion
        # covers orphans, new_apps, reimport_apps, and reload_apps all being empty.
        assert not changes.has_changes
        assert changes.metadata_apps == frozenset({"app1"})
        assert changes.has_any_change

    def test_removed_disabled_app_still_triggers_metadata_broadcast(
        self, detector: AppChangeDetector, make_manifest: Callable
    ) -> None:
        """An app disabled in the original config and deleted entirely from the current config
        must still surface as a metadata change -- `orphans` can't see it (it's derived from the
        enabled-only `original_keys`, which never contained a disabled app), so without a
        metadata signal the removal would produce no broadcast at all and a dashboard's
        persisted row for the deleted app would never refetch.
        """
        original = {"app1": make_manifest("app1", enabled=False)}
        current: dict = {}

        changes = detector.detect_changes(original, current)

        assert not changes.has_changes
        assert changes.metadata_apps == frozenset({"app1"})
        assert changes.has_any_change
        assert "app1" not in changes.orphans
        assert "app1" not in changes.new_apps

    # dup-ignore-start: only_apps guarantee -- new-app metadata still surfaces outside the selection;
    # the sibling only_apps tests share this two-config/detect shape but assert different buckets.
    def test_only_apps_does_not_hide_new_app_metadata_outside_selection(
        self, detector: AppChangeDetector, make_manifest: Callable
    ) -> None:
        """A newly added app outside `only_apps`'s selection is invisible to `new_apps` (it's
        scoped out of lifecycle actions), but it must still surface as a metadata change so a
        dashboard refetches the manifest the framework already persisted for it.
        """
        original: dict = {"app1": make_manifest("app1")}
        current = {"app1": make_manifest("app1"), "app2": make_manifest("app2")}

        changes = detector.detect_changes(original, current, only_apps=frozenset({"app1"}))

        assert "app2" not in changes.new_apps
        assert changes.metadata_apps == frozenset({"app2"})
        # dup-ignore-end

    def test_disabling_an_app_is_still_an_orphan_not_metadata(
        self, detector: AppChangeDetector, make_manifest: Callable
    ) -> None:
        """Toggling an app to disabled must still stop it (orphans), not just broadcast metadata
        -- the enabled-only lifecycle categorization must be unaffected by no longer pre-filtering
        the configs passed into detect_changes().
        """
        original = {"app1": make_manifest("app1", enabled=True)}
        current = {"app1": make_manifest("app1", enabled=False)}

        changes = detector.detect_changes(original, current)

        assert changes.orphans == frozenset({"app1"})
        assert not changes.new_apps
        assert not changes.reload_apps
        assert "app1" not in changes.metadata_apps

    @pytest.mark.parametrize(
        ("companion_field", "companion_old", "companion_new"),
        [
            ("display_name", "Old Name", "New Name"),
            ("app_config", {"setting": "old"}, {"setting": "new"}),
        ],
        ids=["display_name", "app_config"],
    )
    def test_filename_change_with_companion_change_lands_only_in_reimport(
        self,
        detector: AppChangeDetector,
        make_manifest: Callable,
        companion_field: str,
        companion_old: object,
        companion_new: object,
    ) -> None:
        """When a filename change coincides with another change to the same app_key, the app
        lands in exactly one bucket -- reimport_apps. A forced reimport reloads config too, so
        reload_apps would be redundant, and metadata_apps must not double-count an app already
        claimed by a lifecycle category.
        """
        original = {"app1": make_manifest("app1", filename="old_app1.py", **{companion_field: companion_old})}
        current = {"app1": make_manifest("app1", filename="new_app1.py", **{companion_field: companion_new})}

        changes = detector.detect_changes(original, current)

        assert changes.reimport_apps == frozenset({"app1"})
        assert "app1" not in changes.reload_apps
        assert "app1" not in changes.metadata_apps

    def test_new_app_not_in_reload(self, detector: AppChangeDetector, make_manifest: Callable) -> None:
        """Test that new apps are not also in reload_apps."""
        original: dict = {}
        current = {"app1": make_manifest("app1")}

        changes = detector.detect_changes(original, current)

        assert "app1" in changes.new_apps
        assert "app1" not in changes.reload_apps

    # dup-ignore-start: only_apps guarantee -- a non-selected app reads as an orphan;
    # the sibling only_apps tests share this two-config/detect shape but assert different buckets.
    def test_only_apps_parameter_excludes_other_apps(
        self, detector: AppChangeDetector, make_manifest: Callable
    ) -> None:
        """Passing only_apps to detect_changes excludes other apps from current."""
        original = {"app1": make_manifest("app1"), "app2": make_manifest("app2")}
        current = {"app1": make_manifest("app1"), "app2": make_manifest("app2")}

        changes = detector.detect_changes(original, current, only_apps=frozenset({"app1"}))

        # app2 should be seen as orphan since it's filtered out of current
        assert "app2" in changes.orphans
        # dup-ignore-end

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

    # dup-ignore-start: only_apps guarantee -- a non-selected app's config change stays out of reload_apps;
    # the sibling only_apps tests share this two-config/detect shape but assert different buckets.
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
        # dup-ignore-end

    @pytest.mark.parametrize(
        ("field", "old_value", "new_value"),
        [
            ("filename", "old_app1.py", "new_app1.py"),
            ("class_name", "OldApp", "NewApp"),
            ("app_dir", Path("/apps/old"), Path("/apps/new")),
            ("cache_key", "old_key", "new_key"),
        ],
        ids=["filename", "class_name", "app_dir", "cache_key"],
    )
    def test_implementation_field_change_triggers_reimport_not_reload(
        self,
        detector: AppChangeDetector,
        make_manifest: Callable,
        field: str,
        old_value: object,
        new_value: object,
    ) -> None:
        """A change to any single REIMPORT_FIELDS attribute -- with no app_config change and no
        file-watcher event -- lands in reimport_apps rather than reload_apps, so apply_changes()
        forces a class reimport instead of a config-only reload.

        Each field earns that routing differently:

        - `filename` and `class_name` name the app's implementation target directly.
        - `app_dir` moves it just as surely, since `full_path` is `app_dir / filename`, and the
          move is invisible to the file watcher (which reports the changed *configuration* file,
          not the app's new source path).
        - `cache_key` does not change which class loads, but `App.__init__` builds its AsyncCache
          exactly once from it and never rebuilds it. reload_apps's per-instance path only diffs
          app_config, so a cache_key-only change would otherwise silently no-op and leave the
          running instance bound to its old cache path.

        See `REIMPORT_FIELDS` and its docstring in app_change_detector.py.
        """
        original = {"app1": make_manifest("app1", **{field: old_value})}
        current = {"app1": make_manifest("app1", **{field: new_value})}

        changes = detector.detect_changes(original, current)

        assert changes.reimport_apps == frozenset({"app1"})
        assert "app1" not in changes.reload_apps
        assert not changes.orphans
        assert not changes.new_apps
