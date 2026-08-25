"""App change detector for calculating configuration differences."""

import re
from dataclasses import dataclass
from logging import getLogger
from pathlib import Path
from typing import TYPE_CHECKING

from deepdiff import DeepDiff

if TYPE_CHECKING:
    from hassette.config.classes import AppManifest


APP_CONFIG_FIELD = "app_config"
"""The `AppManifest` attribute whose changes should trigger a config reload."""

REIMPORT_FIELDS = ("filename", "class_name", "app_dir", "cache_key")
"""`AppManifest` attributes that require a full app reimport rather than a config-only reload.

`filename`/`class_name`/`app_dir` name the app's implementation target: a change to any of
these means the app must reimport its class from a (possibly new) source file -- `full_path`
(the file the app actually loads from) is `app_dir / filename`, so a change to `app_dir` alone
moves the source file just as surely as a change to `filename`.

`cache_key` is different in kind -- it doesn't affect which class or source file loads, only
where the instance's cache lives. But it still belongs here: `App.__init__` builds its
`AsyncCache` exactly once, keyed on `data_dir / self.cache_key`, and never rebuilds it. A live
edit to `cache_key` alone doesn't touch `app_config`, so `reload_apps`'s per-instance diff (which
only compares `app_config` old-vs-new) would see no change and silently no-op, leaving the
running instance reading and writing its old cache file indefinitely. Routing it through
`reimport_apps` instead forces a full `reload_app(app_key, force_reload=True)`, which rebuilds
the instance -- and its cache -- against the new manifest.

See `REIMPORT_PATH_PATTERN`."""


def _field_path_pattern(*fields: str) -> re.Pattern[str]:
    """Build a regex matching any of ``fields`` as a full DeepDiff path segment.

    Anchors on `.field` so a field name is never matched as a substring of a longer one
    (e.g. `app_config` must not match a future `app_config_overrides` field).
    """
    return re.compile(rf"\.({'|'.join(re.escape(field) for field in fields)})(\[|\.|$)")


APP_CONFIG_PATH_PATTERN = _field_path_pattern(APP_CONFIG_FIELD)
"""Matches `.app_config` as a full path segment -- see `_field_path_pattern`."""

REIMPORT_PATH_PATTERN = _field_path_pattern(*REIMPORT_FIELDS)
"""Matches `.filename`, `.class_name`, `.app_dir`, or `.cache_key` as a full path segment --
see `_field_path_pattern`."""


@dataclass(frozen=True)
class ChangeSet:
    """Immutable set of detected app changes."""

    orphans: frozenset[str]
    """Apps removed from config."""

    new_apps: frozenset[str]
    """Apps added to config."""

    reimport_apps: frozenset[str]
    """Apps needing class reimport (source file content changed, the manifest's implementation
    target -- `filename`/`class_name`/`app_dir` -- changed, or `cache_key` changed)."""

    reload_apps: frozenset[str]
    """Apps needing config reload."""

    @property
    def has_changes(self) -> bool:
        return bool(self.orphans or self.new_apps or self.reimport_apps or self.reload_apps)

    def __repr__(self) -> str:
        return (
            f"ChangeSet(orphans={set(self.orphans)}, new={set(self.new_apps)}, "
            f"reimport={set(self.reimport_apps)}, reload={set(self.reload_apps)})"
        )


class AppChangeDetector:
    """Detects changes between app configurations using DeepDiff."""

    def __init__(self) -> None:
        self.logger = getLogger(f"{__name__}.AppChangeDetector")

    def detect_changes(
        self,
        original_config: dict[str, "AppManifest"],
        current_config: dict[str, "AppManifest"],
        changed_file_paths: frozenset[Path] | None = None,
        only_apps: frozenset[str] | None = None,
    ) -> ChangeSet:
        """Calculate the difference between two configurations.

        Args:
            original_config: The previous app configuration
            current_config: The new app configuration
            changed_file_paths: Paths of files that triggered the change (if any)
            only_apps: When non-empty, restrict change detection to these app keys only

        Returns:
            ChangeSet with categorized changes
        """
        # DeepDiff.include_paths does substring matching against every level visited during
        # traversal (see DeepDiff._skip_this): a level is skipped unless one of the include_paths
        # is a substring of the level's path, or vice versa. "root['app1']" (the level DeepDiff
        # visits on its way down to "root['app1'].app_config") does not contain "app_config" as a
        # substring, so that level is pruned and the traversal never reaches the nested attribute
        # at all -- include_paths can't express "only descend into this specific nested field."
        # Instead, run the diff unrestricted and filter the resulting change tree ourselves,
        # keeping only entries whose path touches the app_config attribute.
        config_diff = DeepDiff(
            original_config,
            current_config,
            ignore_order=True,
        )

        config_changed_keys = {
            item.get_root_key()
            for entries in config_diff.tree.values()
            for item in entries
            if APP_CONFIG_PATH_PATTERN.search(item.path())
        }

        # Apps whose implementation target (filename/class_name/app_dir) or cache_key changed.
        # A live edit to any of these means the app must be fully reimported -- either because
        # its class now loads from a (possibly different) source file, or because its AsyncCache
        # was bound to the old cache_key at construction time and never rebuilds on its own --
        # so these apps route into reimport_apps below, not reload_apps (whose per-instance path
        # only diffs app_config and would silently no-op on a cache_key-only change). The file
        # watcher can't catch the filename/class_name/app_dir case on its own: it reports the
        # changed *configuration* file (e.g. hassette.toml), never the newly-configured source
        # path, so changed_file_paths never contains the app's new full_path either.
        reimport_field_changed_keys = {
            item.get_root_key()
            for entries in config_diff.tree.values()
            for item in entries
            if REIMPORT_PATH_PATTERN.search(item.path())
        }

        original_keys = set(original_config.keys())
        current_keys = set(current_config.keys())

        if only_apps:
            current_keys = current_keys & only_apps

        orphans = original_keys - current_keys
        new_apps = current_keys - original_keys

        # Apps that need reimport due to file change or a reimport-triggering field
        # (filename/class_name/app_dir/cache_key) change. Exclude new apps (they haven't been
        # imported yet) and apps not in current_keys (filtered by only_apps).
        changed = changed_file_paths or frozenset()
        reimport_apps = {
            app.app_key
            for app in current_config.values()
            if app.app_key not in new_apps
            and app.app_key in current_keys
            and (app.full_path in changed or app.app_key in reimport_field_changed_keys)
        }

        # Apps with config changes (excluding those in other categories)
        reload_apps = {
            app_key
            for app_key in config_changed_keys
            if app_key in current_keys
            and app_key not in new_apps
            and app_key not in orphans
            and app_key not in reimport_apps
        }

        return ChangeSet(
            orphans=frozenset(orphans),
            new_apps=frozenset(new_apps),
            reimport_apps=frozenset(reimport_apps),
            reload_apps=frozenset(reload_apps),
        )
