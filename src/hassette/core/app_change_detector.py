"""App change detector for calculating configuration differences."""

from dataclasses import dataclass
from logging import getLogger
from pathlib import Path
from typing import TYPE_CHECKING

from deepdiff import DeepDiff

if TYPE_CHECKING:
    from hassette.config.classes import AppManifest

ROOT_PATH = "root"
USER_CONFIG_PATH = "user_config"


@dataclass(frozen=True)
class ChangeSet:
    """Immutable set of detected app changes."""

    orphans: frozenset[str]
    """Apps removed from config."""

    new_apps: frozenset[str]
    """Apps added to config."""

    reimport_apps: frozenset[str]
    """Apps needing class reimport (file changed)."""

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

    def __init__(self, only_app_filter: str | None = None) -> None:
        self.only_app_filter = only_app_filter
        self.logger = getLogger(f"{__name__}.AppChangeDetector")

    def detect_changes(
        self,
        original_config: dict[str, "AppManifest"],
        current_config: dict[str, "AppManifest"],
        changed_file_paths: frozenset[Path] | None = None,
    ) -> ChangeSet:
        """Calculate the difference between two configurations.

        Args:
            original_config: The previous app configuration
            current_config: The new app configuration
            changed_file_paths: Paths of files that triggered the change (if any)

        Returns:
            ChangeSet with categorized changes
        """
        config_diff = DeepDiff(
            original_config,
            current_config,
            ignore_order=True,
            include_paths=[ROOT_PATH, USER_CONFIG_PATH],
        )

        original_keys = set(original_config.keys())
        current_keys = set(current_config.keys())

        # Apply only_app filter to current keys
        if self.only_app_filter:
            current_keys = {k for k in current_keys if k == self.only_app_filter}

        # Calculate changes
        orphans = original_keys - current_keys
        new_apps = current_keys - original_keys

        # Apps that need reimport due to file change
        # Exclude new apps (they haven't been imported yet) and apps not in current_keys (filtered by only_app)
        changed = changed_file_paths or frozenset()
        reimport_apps = {
            app.app_key
            for app in current_config.values()
            if app.full_path in changed and app.app_key not in new_apps and app.app_key in current_keys
        }

        # Apps with config changes (excluding those in other categories)
        reload_apps = {
            app_key
            for app_key in config_diff.affected_root_keys
            if app_key not in new_apps and app_key not in orphans and app_key not in reimport_apps
        }

        return ChangeSet(
            orphans=frozenset(orphans),
            new_apps=frozenset(new_apps),
            reimport_apps=frozenset(reimport_apps),
            reload_apps=frozenset(reload_apps),
        )

    def set_only_app_filter(self, app_key: str | None) -> None:
        """Update the only_app filter."""
        self.only_app_filter = app_key
