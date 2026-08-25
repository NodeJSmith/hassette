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

IMPLEMENTATION_FIELDS = ("filename", "class_name")
"""`AppManifest` attributes that name the app's implementation target. A change to either
means the app must reimport its class from a (possibly new) source file, not merely reload
its config -- see `IMPLEMENTATION_PATH_PATTERN`."""


def _field_path_pattern(*fields: str) -> re.Pattern[str]:
    """Build a regex matching any of ``fields`` as a full DeepDiff path segment.

    Anchors on `.field` so a field name is never matched as a substring of a longer one
    (e.g. `app_config` must not match a future `app_config_overrides` field).
    """
    return re.compile(rf"\.({'|'.join(re.escape(field) for field in fields)})(\[|\.|$)")


APP_CONFIG_PATH_PATTERN = _field_path_pattern(APP_CONFIG_FIELD)
"""Matches `.app_config` as a full path segment -- see `_field_path_pattern`."""

IMPLEMENTATION_PATH_PATTERN = _field_path_pattern(*IMPLEMENTATION_FIELDS)
"""Matches `.filename` or `.class_name` as a full path segment -- see `_field_path_pattern`."""


@dataclass(frozen=True)
class ChangeSet:
    """Immutable set of detected app changes."""

    orphans: frozenset[str]
    """Apps removed from config."""

    new_apps: frozenset[str]
    """Apps added to config."""

    reimport_apps: frozenset[str]
    """Apps needing class reimport (source file content changed, or the manifest's
    implementation target -- `filename`/`class_name` -- changed)."""

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

        # Apps whose implementation target (filename or class_name) changed. A live edit to
        # either means the app must reimport its class -- possibly from a different file
        # entirely -- so these apps route into reimport_apps below, not reload_apps. The file
        # watcher can't catch this on its own: it reports the changed *configuration* file
        # (e.g. hassette.toml), never the newly-configured source path, so changed_file_paths
        # never contains the app's new full_path either.
        implementation_changed_keys = {
            item.get_root_key()
            for entries in config_diff.tree.values()
            for item in entries
            if IMPLEMENTATION_PATH_PATTERN.search(item.path())
        }

        original_keys = set(original_config.keys())
        current_keys = set(current_config.keys())

        if only_apps:
            current_keys = current_keys & only_apps

        orphans = original_keys - current_keys
        new_apps = current_keys - original_keys

        # Apps that need reimport due to file change or implementation-target (filename/class_name) change
        # Exclude new apps (they haven't been imported yet) and apps not in current_keys (filtered by only_apps)
        changed = changed_file_paths or frozenset()
        reimport_apps = {
            app.app_key
            for app in current_config.values()
            if app.app_key not in new_apps
            and app.app_key in current_keys
            and (app.full_path in changed or app.app_key in implementation_changed_keys)
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
