"""App registry for tracking app state with queryable interface."""

from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum, auto
from typing import TYPE_CHECKING

from hassette.types.enums import ResourceStatus

if TYPE_CHECKING:
    from hassette import AppConfig
    from hassette.app import App
    from hassette.config.classes import AppManifest


class AppInstanceStatus(StrEnum):
    """Fine-grained status for individual app instances."""

    PENDING = auto()
    INITIALIZING = auto()
    RUNNING = auto()
    FAILED = auto()
    STOPPING = auto()
    STOPPED = auto()


@dataclass
class AppInstanceInfo:
    """Snapshot of a single app instance for status queries."""

    app_key: str
    index: int
    instance_name: str
    class_name: str
    status: AppInstanceStatus
    error: Exception | None = None
    error_message: str | None = None


@dataclass
class AppStatusSnapshot:
    """Immutable snapshot of all app states for web UI consumption."""

    running: list[AppInstanceInfo] = field(default_factory=list)
    failed: list[AppInstanceInfo] = field(default_factory=list)
    only_app: str | None = None

    @property
    def total_count(self) -> int:
        return len(self.running) + len(self.failed)

    @property
    def running_count(self) -> int:
        return len(self.running)

    @property
    def failed_count(self) -> int:
        return len(self.failed)


class AppRegistry:
    """Manages app instance state and provides queryable status interface.

    Single source of truth for app state with snapshot generation for web UI.
    """

    def __init__(self) -> None:
        self._apps: dict[str, dict[int, App[AppConfig]]] = defaultdict(dict)
        self._failed_apps: dict[str, list[tuple[int, Exception]]] = defaultdict(list)
        self._manifests: dict[str, AppManifest] = {}
        self._only_app: str | None = None

    # --- State mutation methods ---

    def register_app(self, app_key: str, index: int, app: "App[AppConfig]") -> None:
        """Register a running app instance."""
        self._apps[app_key][index] = app

    def unregister_app(self, app_key: str, index: int | None = None) -> dict[int, "App[AppConfig]"] | None:
        """Remove app instance(s). Returns removed instances."""
        if index is None:
            return self._apps.pop(app_key, None)
        if app_key in self._apps:
            removed = self._apps[app_key].pop(index, None)
            if removed is not None:
                return {index: removed}
        return None

    def record_failure(self, app_key: str, index: int, error: Exception) -> None:
        """Record a failed app startup/crash."""
        self._failed_apps[app_key].append((index, error))

    def clear_failures(self, app_key: str | None = None) -> None:
        """Clear failure records for an app or all apps."""
        if app_key:
            self._failed_apps.pop(app_key, None)
        else:
            self._failed_apps.clear()

    def clear_all(self) -> None:
        """Clear all apps and failures."""
        self._apps.clear()
        self._failed_apps.clear()

    def set_manifests(self, manifests: dict[str, "AppManifest"]) -> None:
        """Update the app manifests configuration."""
        self._manifests = manifests.copy()

    def set_only_app(self, app_key: str | None) -> None:
        """Set the only_app filter."""
        self._only_app = app_key

    # --- Query methods ---

    def get(self, app_key: str, index: int = 0) -> "App[AppConfig] | None":
        """Get a specific app instance."""
        return self._apps.get(app_key, {}).get(index)

    def all_apps(self) -> list["App[AppConfig]"]:
        """Get all running app instances."""
        return [inst for group in self._apps.values() for inst in group.values()]

    def get_apps_by_key(self, app_key: str) -> dict[int, "App[AppConfig]"]:
        """Get all instances for an app key."""
        return self._apps.get(app_key, {}).copy()

    def get_snapshot(self) -> AppStatusSnapshot:
        """Generate immutable status snapshot for web UI."""
        running: list[AppInstanceInfo] = []
        failed: list[AppInstanceInfo] = []

        for app_key, instances in self._apps.items():
            for index, app in instances.items():
                info = AppInstanceInfo(
                    app_key=app_key,
                    index=index,
                    instance_name=app.app_config.instance_name,
                    class_name=app.class_name,
                    status=self._map_resource_status(app.status),
                )
                running.append(info)

        for app_key, failures in self._failed_apps.items():
            for index, error in failures:
                manifest = self._manifests.get(app_key)
                info = AppInstanceInfo(
                    app_key=app_key,
                    index=index,
                    instance_name=f"{manifest.class_name}.{index}" if manifest else f"Unknown.{index}",
                    class_name=manifest.class_name if manifest else "Unknown",
                    status=AppInstanceStatus.FAILED,
                    error=error,
                    error_message=str(error),
                )
                failed.append(info)

        return AppStatusSnapshot(
            running=running,
            failed=failed,
            only_app=self._only_app,
        )

    @staticmethod
    def _map_resource_status(status: ResourceStatus) -> AppInstanceStatus:
        """Map ResourceStatus to AppInstanceStatus."""
        mapping = {
            ResourceStatus.NOT_STARTED: AppInstanceStatus.PENDING,
            ResourceStatus.STARTING: AppInstanceStatus.INITIALIZING,
            ResourceStatus.RUNNING: AppInstanceStatus.RUNNING,
            ResourceStatus.STOPPED: AppInstanceStatus.STOPPED,
            ResourceStatus.FAILED: AppInstanceStatus.FAILED,
            ResourceStatus.CRASHED: AppInstanceStatus.FAILED,
        }
        return mapping.get(status, AppInstanceStatus.FAILED)

    # --- Properties for backwards compatibility ---

    @property
    def apps(self) -> dict[str, dict[int, "App[AppConfig]"]]:
        """Direct access to apps dict (for backwards compatibility)."""
        return self._apps

    @property
    def failed_apps(self) -> dict[str, list[tuple[int, Exception]]]:
        """Direct access to failed_apps dict (for backwards compatibility)."""
        return self._failed_apps

    @property
    def only_app(self) -> str | None:
        return self._only_app

    @property
    def manifests(self) -> dict[str, "AppManifest"]:
        return self._manifests

    @property
    def active_apps_config(self) -> dict[str, "AppManifest"]:
        """Apps that are enabled."""
        enabled_apps = {k: v for k, v in self.manifests.items() if v.enabled}
        if self.only_app:
            enabled_apps = {k: v for k, v in enabled_apps.items() if k == self.only_app}
        return enabled_apps
