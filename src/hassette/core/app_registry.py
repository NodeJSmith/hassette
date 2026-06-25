"""App registry for tracking app state with queryable interface."""

from collections import defaultdict
from logging import getLogger
from typing import TYPE_CHECKING

from hassette.schemas.app_snapshots import AppFullSnapshot, AppInstanceInfo, AppManifestInfo, AppStatusSnapshot
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
        self._only_app: str | None = None
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

    def set_only_app(self, app_key: str | None) -> None:
        """Set the only_app filter."""
        self._only_app = app_key

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
            only_app=self._only_app,
        )

    def get_full_snapshot(self) -> AppFullSnapshot:
        """Generate manifest-based snapshot including all configured apps."""
        manifests: list[AppManifestInfo] = []
        counts = {"running": 0, "failed": 0, "stopped": 0, "disabled": 0, "blocked": 0}

        for app_key, manifest in self._manifests.items():
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

            counts[status] += 1

            instances: list[AppInstanceInfo] = []
            error_message: str | None = None

            if app_key in self._apps:
                for index, app in self._apps[app_key].items():
                    instances.append(self.info_from_running(app_key, index, app))

            error_traceback: str | None = None

            if app_key in self._failed_apps:
                for index, error in self._failed_apps[app_key]:
                    info = self.info_from_failure(app_key, index, error, manifest.class_name)
                    instances.append(info)
                    if error_message is None:
                        error_message = info.error_message
                        error_traceback = info.error_traceback

            block_reason = self._blocked_apps.get(app_key)

            manifests.append(
                AppManifestInfo(
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
            )

        return AppFullSnapshot(
            manifests=manifests,
            only_app=self._only_app,
            total=len(manifests),
            **counts,
        )

    @property
    def apps(self) -> dict[str, dict[int, "App[AppConfig]"]]:
        """Direct access to apps dict (for backwards compatibility)."""
        return self._apps

    @property
    def only_app(self) -> str | None:
        return self._only_app

    @property
    def manifests(self) -> dict[str, "AppManifest"]:
        return self._manifests

    @property
    def enabled_manifests(self) -> dict[str, "AppManifest"]:
        """All enabled app manifests, regardless of only_app filter."""
        return {k: v for k, v in self.manifests.items() if v.enabled}

    @property
    def active_manifests(self) -> dict[str, "AppManifest"]:
        """All active app manifests, considering only_app filter."""
        enabled_apps = {k: v for k, v in self.manifests.items() if v.enabled}
        if self.only_app:
            enabled_apps = {k: v for k, v in enabled_apps.items() if k == self.only_app}
        return enabled_apps

    @property
    def autostart_manifests(self) -> dict[str, "AppManifest"]:
        """Active manifests that should start automatically at boot."""
        return {k: v for k, v in self.active_manifests.items() if v.autostart}
