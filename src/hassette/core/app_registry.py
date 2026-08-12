"""App registry for tracking app state with queryable interface."""

import dataclasses
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from logging import getLogger
from typing import TYPE_CHECKING, Any

from hassette.core.app_factory import AppFactory
from hassette.schemas.app_snapshots import (
    AppFullSnapshot,
    AppInstanceInfo,
    AppManifestInfo,
    AppStatusSnapshot,
    tally_manifest_statuses,
)
from hassette.types.enums import BlockReason, ManifestStatus, ResourceStatus
from hassette.utils.exception_utils import get_traceback_string

if TYPE_CHECKING:
    from hassette import AppConfig
    from hassette.app import App
    from hassette.config.classes import AppManifest


@dataclass(frozen=True)
class InstanceEntry:
    """A single tracked app instance — either running (``app`` set) or failed (``error`` set).

    No ``index`` field — the dict key ``_instances[app_key][index]`` is the single source of
    truth. No stored ``instance_name`` — delegated to the ``App`` object via a property.
    """

    app: "App[AppConfig] | None"
    status: ResourceStatus
    error: Exception | None = None
    error_message: str | None = None
    error_traceback: str | None = None

    @property
    def instance_name(self) -> str | None:
        return self.app.app_config.instance_name if self.app else None


class AppRegistry:
    """Manages app instance state and provides queryable status interface.

    Single source of truth for app state with snapshot generation for web UI.
    """

    def __init__(self) -> None:
        self._instances: dict[str, dict[int, InstanceEntry]] = defaultdict(dict)
        self._blocked_apps: dict[str, BlockReason] = {}
        self._manifests: dict[str, AppManifest] = {}
        self._only_apps: frozenset[str] = frozenset()
        self.logger = getLogger(f"{__name__}.AppRegistry")

    def register_app(self, app_key: str, index: int, app: "App[AppConfig]") -> None:
        """Register a running app instance, replacing any prior entry at that index."""
        self._instances[app_key][index] = InstanceEntry(app=app, status=ResourceStatus.RUNNING)
        self.logger.debug("Registered app '%s' index %d", app_key, index)

    def unregister_app(self, app_key: str, index: int | None = None) -> dict[int, "App[AppConfig]"] | None:
        """Remove app instance(s). Returns removed running instances (failed entries are discarded)."""
        if index is None:
            entries = self._instances.pop(app_key, None)
            if entries is None:
                return None
            return {idx: entry.app for idx, entry in entries.items() if entry.app is not None}

        if app_key not in self._instances:
            return None

        entry = self._instances[app_key].pop(index, None)

        if not self._instances[app_key]:
            del self._instances[app_key]

        if entry is not None and entry.app is not None:
            return {index: entry.app}

        return None

    def record_failure(self, app_key: str, index: int, error: Exception) -> None:
        """Record a failed app startup/crash, replacing any prior entry at that index."""
        self.logger.debug("Recording failure for app '%s' index %d: %s", app_key, index, error)
        self._instances[app_key][index] = InstanceEntry(
            app=None,
            status=ResourceStatus.FAILED,
            error=error,
            error_message=str(error),
            error_traceback=get_traceback_string(error) if error.__traceback__ else None,
        )

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
        """Clear all apps and blocked apps."""
        self._instances.clear()
        self._blocked_apps.clear()

    def set_manifests(self, manifests: dict[str, "AppManifest"]) -> None:
        """Update the app manifests configuration."""
        self._manifests = manifests.copy()

    def set_only_apps(self, app_keys: Iterable[str]) -> None:
        """Set the exclusive-app filter. An empty iterable clears it."""
        self._only_apps = frozenset(app_keys)

    def __contains__(self, app_key: str) -> bool:
        return any(entry.app is not None for entry in self._instances.get(app_key, {}).values())

    def app_keys(self) -> list[str]:
        """Get all app keys with at least one running instance."""
        return [
            app_key
            for app_key, entries in self._instances.items()
            if any(entry.app is not None for entry in entries.values())
        ]

    def get(self, app_key: str, index: int = 0) -> "App[AppConfig] | None":
        """Get a specific running app instance."""
        entry = self._instances.get(app_key, {}).get(index)
        return entry.app if entry is not None else None

    def get_manifest(self, app_key: str) -> "AppManifest | None":
        """Get the manifest for an app key."""
        return self._manifests.get(app_key)

    def all_apps(self) -> list["App[AppConfig]"]:
        """Get all running app instances."""
        return [
            entry.app for entries in self._instances.values() for entry in entries.values() if entry.app is not None
        ]

    def get_running_apps(self, app_key: str) -> dict[int, "App[AppConfig]"]:
        """Get all running instances for an app key (excludes failed entries)."""
        return {idx: entry.app for idx, entry in self._instances.get(app_key, {}).items() if entry.app is not None}

    def get_instances(self, app_key: str) -> dict[int, InstanceEntry]:
        """Get all entries (running and failed) for an app key."""
        return self._instances.get(app_key, {}).copy()

    def _resolve_failed_instance_name(self, app_key: str, index: int, manifest: "AppManifest | None") -> str:
        """Resolve the configured ``instance_name`` for a failed entry from manifest config."""
        if manifest is None:
            return f"Unknown.{index}"

        configs = AppFactory.normalize_configs(manifest.app_config)
        if index < len(configs):
            return configs[index].get("instance_name", f"{manifest.class_name}.{index}")
        return f"{manifest.class_name}.{index}"

    def _info_from_entry(
        self, app_key: str, index: int, entry: InstanceEntry, manifest: "AppManifest | None" = None
    ) -> AppInstanceInfo:
        if entry.app is not None:
            return AppInstanceInfo(
                app_key=app_key,
                index=index,
                instance_name=entry.app.app_config.instance_name,
                class_name=entry.app.class_name,
                status=entry.app.status,
                owner_id=entry.app.unique_name,
            )

        class_name = manifest.class_name if manifest else "Unknown"
        return AppInstanceInfo(
            app_key=app_key,
            index=index,
            instance_name=self._resolve_failed_instance_name(app_key, index, manifest),
            class_name=class_name,
            status=ResourceStatus.FAILED,
            error=entry.error,
            error_message=entry.error_message,
            error_traceback=entry.error_traceback,
        )

    def get_snapshot(self) -> AppStatusSnapshot:
        """Generate immutable status snapshot for web UI."""
        running: list[AppInstanceInfo] = []
        failed: list[AppInstanceInfo] = []

        for app_key, entries in self._instances.items():
            manifest = self._manifests.get(app_key)
            for index, entry in entries.items():
                info = self._info_from_entry(app_key, index, entry, manifest)
                if entry.app is not None:
                    running.append(info)
                else:
                    failed.append(info)

        return AppStatusSnapshot(
            running=running,
            failed=failed,
            only_apps=sorted(self._only_apps),
        )

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
        entries = self._instances.get(app_key, {})
        has_running = any(entry.app is not None for entry in entries.values())
        has_failed = any(entry.status == ResourceStatus.FAILED for entry in entries.values())

        if not manifest.enabled:
            status = ManifestStatus.DISABLED
        elif app_key in self._blocked_apps:
            status = ManifestStatus.BLOCKED
        elif has_running and has_failed:
            status = ManifestStatus.DEGRADED
        elif has_running:
            status = ManifestStatus.RUNNING
        elif has_failed:
            status = ManifestStatus.FAILED
        else:
            status = ManifestStatus.STOPPED

        instances: list[AppInstanceInfo] = []
        error_message: str | None = None
        error_traceback: str | None = None

        for index, entry in entries.items():
            info = self._info_from_entry(app_key, index, entry, manifest)
            instances.append(info)
            if entry.app is None and error_message is None:
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
      ``build_manifest_info()`` (priority: disabled > blocked > degraded > running > failed >
      stopped), and ``in_current_config`` is ``True``.
    - If absent (a DB-only / removed app): status defaults to ``"stopped"`` with zero
      instances, and ``in_current_config`` is ``False``.

    Static metadata (``class_name``, ``display_name``, ``filename``, ``autostart``,
    ``auto_loaded``) always comes from the DB row, never from the in-memory manifest — the DB
    is the source of truth for metadata, the registry is the source of truth for live status.
    ``enabled`` is the exception: it is also the highest-priority input to the registry's
    status derivation (``disabled > blocked > degraded > running > failed > stopped``), so
    when the app is in-memory it is sourced from the registry alongside ``status`` —
    otherwise a stale DB row could produce a response where ``status == "disabled"`` but
    ``enabled == True`` (or vice versa), a state ``build_manifest_info()`` itself could never
    construct.

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
        static_fields = {
            "class_name": db_row["class_name"],
            "display_name": db_row["display_name"],
            "filename": db_row["filename"],
            "auto_loaded": bool(db_row["auto_loaded"]),
            "autostart": bool(db_row["autostart"]),
        }

        if in_memory_manifest is not None:
            # Static metadata still comes from the DB row (source of truth for config);
            # the computed runtime fields (status/instances/...) come from `derived`, and
            # `enabled` also comes from `derived` since it drives `derived.status` — keeping
            # both on the same source prevents a stale-DB `enabled` from disagreeing with a
            # freshly-derived `status`.
            derived = registry.build_manifest_info(app_key, in_memory_manifest)
            info = dataclasses.replace(derived, app_key=app_key, in_current_config=True, **static_fields)
        else:
            info = AppManifestInfo(
                app_key=app_key,
                status="stopped",
                enabled=bool(db_row["enabled"]),
                in_current_config=False,
                **static_fields,
            )

        results.append(info)

    return results
