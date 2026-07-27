"""App registry for tracking app state with queryable interface."""

from collections import defaultdict
from collections.abc import Iterable
from logging import getLogger
from typing import TYPE_CHECKING, Any

from hassette.schemas.app_snapshots import (
    AppFullSnapshot,
    AppInstanceInfo,
    AppManifestInfo,
    AppStatusSnapshot,
    tally_manifest_statuses,
)
from hassette.types.enums import BlockReason, ResourceStatus
from hassette.utils.exception_utils import get_traceback_string

if TYPE_CHECKING:
    from hassette import AppConfig
    from hassette.app import App
    from hassette.config.classes import AppManifest


class AppRegistry:
    """Manages app instance state and provides queryable status interface.

    Single source of truth for app state with snapshot generation for web UI.
    """

    def __init__(self) -> None:
        self._apps: dict[str, dict[int, App[AppConfig]]] = defaultdict(dict)
        self._failed_apps: dict[str, list[tuple[int, Exception]]] = defaultdict(list)
        self._blocked_apps: dict[str, BlockReason] = {}
        self._manifests: dict[str, AppManifest] = {}
        self._only_apps: frozenset[str] = frozenset()
        self.logger = getLogger(f"{__name__}.AppRegistry")

    def register_app(self, app_key: str, index: int, app: "App[AppConfig]") -> None:
        """Register a running app instance."""
        if app_key in self._failed_apps and index in [idx for idx, _ in self._failed_apps[app_key]]:
            # Clear any previous failures for this app_key
            self.logger.debug("Clearing previous failure records for app '%s' index %d", app_key, index)
            self._failed_apps.pop(app_key)

        self._apps[app_key][index] = app
        self.logger.debug("Registered app '%s' index %d", app_key, index)

    def unregister_app(self, app_key: str, index: int | None = None) -> dict[int, "App[AppConfig]"] | None:
        """Remove app instance(s). Returns removed instances."""
        if index is None:
            return self._apps.pop(app_key, None)

        removed = None

        if app_key in self._apps:
            removed = self._apps[app_key].pop(index, None)

        if not self._apps.get(app_key):
            del self._apps[app_key]

        if removed is not None:
            return {index: removed}

        return None

    def record_failure(self, app_key: str, index: int, error: Exception) -> None:
        """Record a failed app startup/crash."""
        if app_key in self._apps and index in self._apps[app_key]:
            # Remove from running apps if present
            self.logger.debug("Removing running app '%s' index %d due to failure", app_key, index)
            self._apps[app_key].pop(index)
            if not self._apps.get(app_key):
                del self._apps[app_key]

        self.logger.debug("Recording failure for app '%s' index %d: %s", app_key, index, error)

        self._failed_apps[app_key].append((index, error))

    def clear_failures(self, app_key: str | None = None) -> None:
        """Clear failure records for an app or all apps."""
        if app_key:
            self._failed_apps.pop(app_key, None)
        else:
            self._failed_apps.clear()

    def block_app(self, app_key: str, reason: BlockReason) -> None:
        """Record that an app was intentionally not started."""
        self._blocked_apps[app_key] = reason
        self.logger.debug("Blocked app '%s' reason: %s", app_key, reason)

    def unblock_apps(self, reason: BlockReason) -> set[str]:
        """Remove and return all apps blocked for the given reason."""
        matching = {k for k, r in self._blocked_apps.items() if r == reason}
        for k in matching:
            del self._blocked_apps[k]
        return matching

    def clear_all(self) -> None:
        """Clear all apps, failures, and blocked apps."""
        self._apps.clear()
        self._failed_apps.clear()
        self._blocked_apps.clear()

    def set_manifests(self, manifests: dict[str, "AppManifest"]) -> None:
        """Update the app manifests configuration."""
        self._manifests = manifests.copy()

    def set_only_apps(self, app_keys: Iterable[str]) -> None:
        """Set the exclusive-app filter. An empty iterable clears it."""
        self._only_apps = frozenset(app_keys)

    def __contains__(self, app_key: str) -> bool:
        return app_key in self._apps

    def app_keys(self) -> list[str]:
        """Get all app keys with at least one running instance."""
        return list(self._apps.keys())

    def get(self, app_key: str, index: int = 0) -> "App[AppConfig] | None":
        """Get a specific app instance."""
        return self._apps.get(app_key, {}).get(index)

    def get_manifest(self, app_key: str) -> "AppManifest | None":
        """Get the manifest for an app key."""
        return self._manifests.get(app_key)

    def all_apps(self) -> list["App[AppConfig]"]:
        """Get all running app instances."""
        return [inst for group in self._apps.values() for inst in group.values()]

    def get_apps_by_key(self, app_key: str) -> dict[int, "App[AppConfig]"]:
        """Get all instances for an app key."""
        return self._apps.get(app_key, {}).copy()

    def iter_all_instances(self) -> list[tuple[str, int, "App[AppConfig]"]]:
        """Yield (app_key, index, app) for every running instance."""
        return [(app_key, index, app) for app_key, instances in self._apps.items() for index, app in instances.items()]

    def info_from_running(self, app_key: str, index: int, app: "App[AppConfig]") -> AppInstanceInfo:
        return AppInstanceInfo(
            app_key=app_key,
            index=index,
            instance_name=app.app_config.instance_name,
            class_name=app.class_name,
            status=app.status,
            owner_id=app.unique_name,
        )

    def info_from_failure(
        self, app_key: str, index: int, error: Exception, class_name: str = "Unknown"
    ) -> AppInstanceInfo:
        return AppInstanceInfo(
            app_key=app_key,
            index=index,
            instance_name=f"{class_name}.{index}",
            class_name=class_name,
            status=ResourceStatus.FAILED,
            error=error,
            error_message=str(error),
            error_traceback=get_traceback_string(error) if error.__traceback__ else None,
        )

    def get_snapshot(self) -> AppStatusSnapshot:
        """Generate immutable status snapshot for web UI."""
        running = [
            self.info_from_running(app_key, index, app)
            for app_key, instances in self._apps.items()
            for index, app in instances.items()
        ]
        failed = []
        for app_key, failures in self._failed_apps.items():
            manifest = self._manifests.get(app_key)
            cls_name = manifest.class_name if manifest else "Unknown"
            for index, error in failures:
                failed.append(self.info_from_failure(app_key, index, error, cls_name))

        return AppStatusSnapshot(
            running=running,
            failed=failed,
            only_apps=sorted(self._only_apps),
        )

    def get_manifest_snapshot(self, app_key: str) -> AppManifestInfo | None:
        """Generate a snapshot for a single app manifest, or None if not found."""
        manifest = self._manifests.get(app_key)
        if manifest is None:
            return None
        return self.build_manifest_info(app_key, manifest)

    def get_full_snapshot(self) -> AppFullSnapshot:
        """Generate manifest-based snapshot including all configured apps."""
        manifests = [self.build_manifest_info(app_key, manifest) for app_key, manifest in self._manifests.items()]

        return AppFullSnapshot(
            manifests=manifests,
            only_apps=sorted(self._only_apps),
            total=len(manifests),
            **tally_manifest_statuses(manifests),
        )

    def build_manifest_info(self, app_key: str, manifest: "AppManifest") -> AppManifestInfo:
        if not manifest.enabled:
            status = "disabled"
        elif app_key in self._blocked_apps:
            status = "blocked"
        elif self._apps.get(app_key):
            status = "running"
        elif self._failed_apps.get(app_key):
            status = "failed"
        else:
            status = "stopped"

        instances: list[AppInstanceInfo] = []
        error_message: str | None = None
        error_traceback: str | None = None

        if app_key in self._apps:
            for index, app in self._apps[app_key].items():
                instances.append(self.info_from_running(app_key, index, app))

        if app_key in self._failed_apps:
            for index, error in self._failed_apps[app_key]:
                info = self.info_from_failure(app_key, index, error, manifest.class_name)
                instances.append(info)
                if error_message is None:
                    error_message = info.error_message
                    error_traceback = info.error_traceback

        block_reason = self._blocked_apps.get(app_key)

        return AppManifestInfo(
            app_key=app_key,
            class_name=manifest.class_name,
            display_name=manifest.display_name,
            filename=manifest.filename,
            enabled=manifest.enabled,
            auto_loaded=manifest.auto_loaded,
            status=status,
            autostart=manifest.autostart,
            block_reason=block_reason.value if block_reason else None,
            instance_count=len(instances),
            instances=instances,
            error_message=error_message,
            error_traceback=error_traceback,
        )

    @property
    def only_apps(self) -> frozenset[str]:
        return self._only_apps

    @property
    def manifests(self) -> dict[str, "AppManifest"]:
        return self._manifests

    @property
    def enabled_manifests(self) -> dict[str, "AppManifest"]:
        """All enabled app manifests, regardless of the exclusive-app filter."""
        return {k: v for k, v in self.manifests.items() if v.enabled}

    @property
    def active_manifests(self) -> dict[str, "AppManifest"]:
        """All active app manifests, considering the exclusive-app filter."""
        enabled_apps = self.enabled_manifests
        if self._only_apps:
            enabled_apps = {k: v for k, v in enabled_apps.items() if k in self._only_apps}
        return enabled_apps

    @property
    def autostart_manifests(self) -> dict[str, "AppManifest"]:
        """Active manifests that should start automatically at boot."""
        return {k: v for k, v in self.active_manifests.items() if v.autostart}


def overlay_runtime_state(db_rows: list[dict[str, Any]], registry: AppRegistry) -> list[AppManifestInfo]:
    """Merge DB-persisted manifest rows with in-memory runtime state.

    The single overlay function all web routes call to combine the DB app spine with live
    status — see the design doc's "Web route refactoring" section. For each DB row, checks
    whether the app is present in ``registry``'s in-memory manifests:

    - If present: status/instances are derived from the registry's live state via
      ``build_manifest_info()`` (priority: disabled > blocked > running > failed > stopped),
      and ``in_current_config`` is ``True``.
    - If absent (a DB-only / removed app): status defaults to ``"stopped"`` with zero
      instances, and ``in_current_config`` is ``False``.

    Static metadata (``class_name``, ``display_name``, ``filename``, ``enabled``,
    ``autostart``, ``auto_loaded``) always comes from the DB row, never from the in-memory
    manifest — the DB is the source of truth for metadata, the registry is the source of
    truth for live status.

    Args:
        db_rows: Rows from ``get_all_app_manifests()`` or a single-row list from
            ``get_app_manifest()``. Boolean columns arrive as SQLite ints (0/1), not Python
            bools — this function coerces them explicitly since ``AppManifestInfo`` is a
            dataclass (no Pydantic-style auto-coercion).
        registry: The in-memory ``AppRegistry`` to overlay runtime state from.

    Returns:
        One ``AppManifestInfo`` per DB row, in the same order as ``db_rows``.
    """
    results: list[AppManifestInfo] = []

    for db_row in db_rows:
        app_key = db_row["app_key"]
        in_memory_manifest = registry.manifests.get(app_key)

        if in_memory_manifest is not None:
            derived = registry.build_manifest_info(app_key, in_memory_manifest)
            status = derived.status
            instances = derived.instances
            instance_count = derived.instance_count
            block_reason = derived.block_reason
            error_message = derived.error_message
            error_traceback = derived.error_traceback
            in_current_config = True
        else:
            status = "stopped"
            instances = []
            instance_count = 0
            block_reason = None
            error_message = None
            error_traceback = None
            in_current_config = False

        results.append(
            AppManifestInfo(
                app_key=app_key,
                class_name=db_row["class_name"],
                display_name=db_row["display_name"],
                filename=db_row["filename"],
                enabled=bool(db_row["enabled"]),
                auto_loaded=bool(db_row["auto_loaded"]),
                status=status,
                autostart=bool(db_row["autostart"]),
                block_reason=block_reason,
                instance_count=instance_count,
                instances=instances,
                error_message=error_message,
                error_traceback=error_traceback,
                in_current_config=in_current_config,
            )
        )

    return results
