"""App registry for tracking app state with queryable interface."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace
from logging import getLogger
from typing import TYPE_CHECKING, Any

from hassette_wire import AppStatus, ResourceStatus

from hassette.core.app_factory import AppFactory
from hassette.schemas.app_snapshots import (
    AppFullSnapshot,
    AppInstanceInfo,
    AppManifestInfo,
    AppStatusSnapshot,
    NeedsRestartInfo,
    is_failed_info,
    tally_app_statuses,
)
from hassette.types.enums import BlockReason
from hassette.utils import date_utils
from hassette.utils.exception_utils import get_traceback_string

if TYPE_CHECKING:
    from hassette import AppConfig
    from hassette.app import App
    from hassette.config.classes import AppManifest

UNKNOWN_LABEL = "Unknown"


@dataclass(frozen=True)
class InstanceEntry:
    """A single tracked app instance — either running (``app`` set) or failed (``error`` set).

    No ``index`` field — the dict key ``_instances[app_key][index]`` is the single source of
    truth. No stored ``instance_name`` — callers read it off the ``App`` object directly
    (``entry.app.app_config.instance_name``) or via ``_resolve_instance_name()`` for
    failed entries, which have no ``App``.
    """

    app: "App[AppConfig] | None"
    status: ResourceStatus
    error: Exception | None = None
    error_message: str | None = None
    error_traceback: str | None = None

    @property
    def is_running(self) -> bool:
        """Whether this entry holds a live ``App`` (as opposed to a recorded failure)."""
        return self.app is not None


@dataclass(frozen=True)
class NeedsRestartRecord:
    """A needs-restart flag on one ``(app_key, index)``, kept outside the instance map.

    Stores the instance and class name so the row still renders after its entry is unregistered or its
    app leaves config.
    """

    instance_name: str
    class_name: str
    info: NeedsRestartInfo


class AppRegistry:
    """Manages app instance state and provides queryable status interface.

    Single source of truth for app state with snapshot generation for web UI.

    Per-index state has two parts: the instance entry (running or failed) and an optional needs-restart
    record. ``resolve_instance_info`` is the one place they combine; every per-index reader goes through it.
    """

    def __init__(self) -> None:
        self._instances: dict[str, dict[int, InstanceEntry]] = defaultdict(dict)
        self._needs_restart: dict[str, dict[int, NeedsRestartRecord]] = defaultdict(dict)
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
            return {idx: app for idx, entry in entries.items() if (app := entry.app) is not None}

        if app_key not in self._instances:
            return None

        entry = self._instances[app_key].pop(index, None)

        if not self._instances[app_key]:
            del self._instances[app_key]

        if entry is not None and (app := entry.app) is not None:
            return {index: app}

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

    def flag_needs_restart(
        self,
        app_key: str,
        index: int,
        *,
        instance_name: str,
        class_name: str,
        reason: str,
        pending_tasks: Iterable[str] = (),
    ) -> bool:
        """Record that ``(app_key, index)`` needs a hassette restart because work may still be running.

        The first record at an index stands until restart: a later flag at the same index is not merged
        in, and returns ``False``. Survives ``unregister_app``, ``record_failure`` and config changes;
        only ``clear_all`` (process exit, test reset) removes it.

        Returns:
            ``True`` when this call created the record.
        """
        records = self._needs_restart[app_key]
        if index in records:
            return False
        records[index] = NeedsRestartRecord(
            instance_name=instance_name,
            class_name=class_name,
            info=NeedsRestartInfo(reason=reason, pending_tasks=tuple(pending_tasks), flagged_at=date_utils.now()),
        )
        self.logger.debug("Flagged app '%s' index %d needs restart: %s", app_key, index, reason)
        return True

    def get_needs_restart(self, app_key: str, index: int) -> NeedsRestartRecord | None:
        """The needs-restart record at ``(app_key, index)``, or ``None`` when that index isn't flagged."""
        return self._needs_restart.get(app_key, {}).get(index)

    def refusal_reason(self, app_key: str, index: int) -> str | None:
        """Why an action is refused at a flagged ``(app_key, index)``, or ``None`` when it isn't flagged.

        The ``reason`` of every refused outcome, so a refusal reads the same on every path. It carries the flag's
        time and reason, which match the ERROR logged when the index was flagged.
        """
        record = self.get_needs_restart(app_key, index)
        if record is None:
            return None
        return f"needs a hassette restart (flagged at {record.info.flagged_at}: {record.info.reason})"

    def instance_name(self, app_key: str, index: int) -> str:
        """The name of ``(app_key, index)``: its tracked instance's, or its configured one when nothing is tracked."""
        info = self.resolve_instance_info(app_key, index)
        if info is not None:
            return info.instance_name
        return self._resolve_instance_name(app_key, index, self._manifests.get(app_key))

    def resolve_instance_info(
        self, app_key: str, index: int, manifest: "AppManifest | None" = None
    ) -> AppInstanceInfo | None:
        """The effective snapshot of one ``(app_key, index)``, or ``None`` when nothing is tracked there.

        The one place an instance entry and its needs-restart record combine. A record wins whatever the
        entry says: the result is FAILED with ``needs_restart`` set, and when the entry holds no error
        message the record's reason serves as it. Without a record, the result is the entry's.

        ``manifest`` names and ranges the index; it defaults to the loaded manifest for ``app_key``.
        """
        manifest = manifest or self._manifests.get(app_key)
        entry = self._instances.get(app_key, {}).get(index)
        record = self.get_needs_restart(app_key, index)
        if record is None:
            return self._info_from_entry(app_key, index, entry, manifest) if entry is not None else None

        if entry is not None:
            base = self._info_from_entry(app_key, index, entry, manifest)
        else:
            base = AppInstanceInfo(
                app_key=app_key,
                index=index,
                instance_name=record.instance_name,
                class_name=record.class_name,
                status=ResourceStatus.FAILED,
                in_current_config=self._index_in_current_config(index, manifest),
            )
        return replace(
            base,
            status=ResourceStatus.FAILED,
            error_message=base.error_message or record.info.reason,
            needs_restart=record.info,
        )

    def tracked_indices(self, app_key: str) -> set[int]:
        """Indices with an instance entry or a needs-restart record for ``app_key``."""
        return set(self._instances.get(app_key, {})) | set(self._needs_restart.get(app_key, {}))

    def resolve_instance_infos(self, app_key: str, manifest: "AppManifest | None" = None) -> dict[int, AppInstanceInfo]:
        """``resolve_instance_info`` for every tracked index of ``app_key``, in index order."""
        return {
            index: info
            for index in sorted(self.tracked_indices(app_key))
            if (info := self.resolve_instance_info(app_key, index, manifest)) is not None
        }

    def prune_stale_failed_indices(self, app_key: str, valid_index_count: int) -> dict[int, AppInstanceInfo]:
        """Remove failed (non-running) entries at indices no longer present in the current config.

        Returns what was removed, resolved to ``AppInstanceInfo`` (same as ``get_failed_instance_infos``).
        A needs-restart record at a pruned index is kept, so its resolved snapshot stays FAILED.

        Config can shrink (fewer configured instances) without the app going through a full
        reload — e.g. an ``autostart=false`` app that isn't auto-reconciled on a config change
        (see ``AppLifecycleService.should_auto_reconcile``) and is later started manually.
        ``AppFactory.create_instances()`` only ever touches indices within the current config, so
        without this, a failed entry at a since-removed index lingers in the registry forever,
        misreporting the app as degraded/failed even after it starts cleanly at its remaining
        index. Running entries are untouched — an orphaned *running* instance needs an actual
        shutdown, not just a registry removal, which is out of scope here.

        The return value lets the caller emit a status-change event for each removed entry —
        callers must not discard entries silently (see ``AppLifecycleService._stop_app_unlocked``
        for why: the WS status cache never learns otherwise, and stays on FAILED forever).
        """
        entries = self._instances.get(app_key)
        if not entries:
            return {}
        stale_indices = [
            index for index, entry in entries.items() if not entry.is_running and index >= valid_index_count
        ]
        pruned = {index: info for index in stale_indices if (info := self.resolve_instance_info(app_key, index))}
        for index in stale_indices:
            del entries[index]
        if not entries:
            del self._instances[app_key]
        return pruned

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

    def is_blocked(self, app_key: str) -> bool:
        """Whether ``app_key`` is currently blocked (e.g. excluded by the ``--app`` filter).

        The authoritative check for the manual start/reload actions in
        ``AppLifecycleService`` — a blocked app's manifest still exists (and still has a
        configured instance count), so it stays addressable by index-range and
        already-running checks alone; only this check stops a manual start/reload from
        bypassing the exclusive-app filter.
        """
        return app_key in self._blocked_apps

    def clear_all(self) -> None:
        """Clear all apps, blocked apps, and needs-restart records (process exit and test reset only)."""
        self._instances.clear()
        self._blocked_apps.clear()
        self._needs_restart.clear()

    def set_manifests(self, manifests: dict[str, "AppManifest"]) -> None:
        """Update the app manifests configuration."""
        self._manifests = manifests.copy()

    def set_only_apps(self, app_keys: Iterable[str]) -> None:
        """Set the exclusive-app filter. An empty iterable clears it."""
        self._only_apps = frozenset(app_keys)

    def __contains__(self, app_key: str) -> bool:
        return any(entry.is_running for entry in self._instances.get(app_key, {}).values())

    def app_keys(self) -> list[str]:
        """Get all app keys with at least one running instance."""
        return [
            app_key
            for app_key, entries in self._instances.items()
            if any(entry.is_running for entry in entries.values())
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
            app for entries in self._instances.values() for entry in entries.values() if (app := entry.app) is not None
        ]

    def get_running_apps(self, app_key: str) -> dict[int, "App[AppConfig]"]:
        """Get all running instances for an app key (excludes failed entries)."""
        return {idx: app for idx, entry in self._instances.get(app_key, {}).items() if (app := entry.app) is not None}

    def get_instances(self, app_key: str) -> dict[int, InstanceEntry]:
        """Get all entries (running and failed) for an app key."""
        return self._instances.get(app_key, {}).copy()

    def get_failed_instance_infos(self, app_key: str) -> dict[int, AppInstanceInfo]:
        """Get resolved AppInstanceInfo for failed indices of an app key: failed entries and flagged indices.

        Used to emit a status-change event for failures recorded by ``AppFactory.create_instances()``
        before an ``App`` object existed to build the event from — reuses the same instance_name/
        class_name resolution as snapshot generation so the event matches what a subsequent fetch
        would show.
        """
        return {index: info for index, info in self.resolve_instance_infos(app_key).items() if is_failed_info(info)}

    @staticmethod
    def _index_in_current_config(index: int, manifest: "AppManifest | None") -> bool:
        # Without a manifest there is no configured range to compare against; the app-level
        # ``AppManifestInfo.in_current_config`` covers a wholly orphaned app.
        return manifest is None or index < len(AppFactory.normalize_configs(manifest.app_config))

    def _resolve_instance_name(self, app_key: str, index: int, manifest: "AppManifest | None") -> str:
        """Resolve the configured ``instance_name`` for an index with no live ``App`` object.

        That is a failed entry, or an index that isn't tracked in the registry at all.

        An index past the manifest's configured instances has no name; it gets a display label
        that can never pass instance-name validation, so it can't be mistaken for a real name.
        """
        if manifest is None:
            return f"{UNKNOWN_LABEL}.{index}"

        configs = AppFactory.normalize_configs(manifest.app_config)
        if index < len(configs):
            return configs[index]["instance_name"]
        return f"{manifest.class_name}.{index}"

    def _info_from_entry(
        self, app_key: str, index: int, entry: InstanceEntry, manifest: "AppManifest | None" = None
    ) -> AppInstanceInfo:
        in_current_config = self._index_in_current_config(index, manifest)
        if (app := entry.app) is not None:
            return AppInstanceInfo(
                app_key=app_key,
                index=index,
                instance_name=app.app_config.instance_name,
                class_name=app.class_name,
                status=app.status,
                owner_id=app.unique_name,
                in_current_config=in_current_config,
            )

        class_name = manifest.class_name if manifest else UNKNOWN_LABEL
        return AppInstanceInfo(
            app_key=app_key,
            index=index,
            instance_name=self._resolve_instance_name(app_key, index, manifest),
            class_name=class_name,
            status=ResourceStatus.FAILED,
            error=entry.error,
            error_message=entry.error_message,
            error_traceback=entry.error_traceback,
            in_current_config=in_current_config,
        )

    def get_snapshot(self) -> AppStatusSnapshot:
        """Generate immutable status snapshot for web UI."""
        # Every app key with an instance entry or a needs-restart record, in first-seen order.
        app_keys = dict.fromkeys([*self._instances, *self._needs_restart])
        instances = [info for app_key in app_keys for info in self.resolve_instance_infos(app_key).values()]

        return AppStatusSnapshot(
            instances=tuple(instances),
            only_apps=tuple(sorted(self._only_apps)),
        )

    def get_full_snapshot(self) -> AppFullSnapshot:
        """Generate manifest-based snapshot including all configured apps."""
        manifests = [self.build_manifest_info(app_key, manifest) for app_key, manifest in self._manifests.items()]

        return AppFullSnapshot(
            manifests=tuple(manifests),
            only_apps=tuple(sorted(self._only_apps)),
            total=len(manifests),
            status_counts=tally_app_statuses(manifests),
        )

    def build_manifest_info(self, app_key: str, manifest: "AppManifest") -> AppManifestInfo:
        """Build a manifest snapshot whose ``instances`` covers every *configured* instance.

        This includes configured instances beyond the ones currently tracked in the registry.

        A configured index with no registry entry (never started, or independently stopped via
        ``AppLifecycleService.stop_instance()``) gets a synthetic ``ResourceStatus.STOPPED``
        placeholder so it stays addressable by the CLI and visible in the web UI instead of
        silently disappearing from ``instances`` once its instance is no longer tracked. A
        tracked index outside the current config range (an orphaned running instance mid config
        shrink — see ``prune_stale_failed_indices``) is still included too: this is a union of
        tracked and configured indices, never a plain ``range(configured_count)``, so a live
        orphan is never dropped from view.

        ``status`` (RUNNING/FAILED/DEGRADED/STOPPED/...) is derived from tracked indices only
        (entries and needs-restart records, through ``resolve_instance_info``) — a
        configured-but-not-yet-started app is correctly STOPPED, not DEGRADED, even though
        ``instances`` also lists its not-yet-tracked instances. A flagged index counts as failed.
        """
        tracked = self.resolve_instance_infos(app_key, manifest)
        has_running = any(not is_failed_info(info) for info in tracked.values())
        has_failed = any(is_failed_info(info) for info in tracked.values())

        if not manifest.enabled:
            status = AppStatus.DISABLED
        elif app_key in self._blocked_apps:
            status = AppStatus.BLOCKED
        elif has_running and has_failed:
            status = AppStatus.DEGRADED
        elif has_running:
            status = AppStatus.RUNNING
        elif has_failed:
            status = AppStatus.FAILED
        else:
            status = AppStatus.STOPPED

        configured_count = len(AppFactory.normalize_configs(manifest.app_config))
        all_indices = sorted(set(tracked) | set(range(configured_count)))

        instances: list[AppInstanceInfo] = []
        error_message: str | None = None
        error_traceback: str | None = None

        for index in all_indices:
            info = tracked.get(index)
            if info is not None:
                if is_failed_info(info) and error_message is None:
                    error_message = info.error_message
                    error_traceback = info.error_traceback
            else:
                info = AppInstanceInfo(
                    app_key=app_key,
                    index=index,
                    instance_name=self._resolve_instance_name(app_key, index, manifest),
                    class_name=manifest.class_name,
                    status=ResourceStatus.STOPPED,
                )
            instances.append(info)

        block_reason = self._blocked_apps.get(app_key)

        return AppManifestInfo(
            app_key=app_key,
            class_name=manifest.class_name,
            display_name=manifest.display_name,
            description=manifest.description,
            filename=manifest.filename,
            enabled=manifest.enabled,
            status=status,
            autostart=manifest.autostart,
            block_reason=block_reason.value if block_reason else None,
            instance_count=len(instances),
            instances=tuple(instances),
            error_message=error_message,
            error_traceback=error_traceback,
            needs_restart_count=count_needs_restart(instances),
        )

    def build_orphaned_flag_info(self, app_key: str) -> AppManifestInfo | None:
        """Runtime fields for an app absent from the loaded config that still has needs-restart records.

        Returns ``None`` when the app has no record. A record makes its index tracked, and the resolver
        returns an info for every flagged index, so ``instances`` is never empty past the guard.

        ``display_name``, ``filename`` and ``enabled`` are placeholders: static metadata is the caller's
        to fill in (``overlay_runtime_state`` overrides them from the DB row).
        """
        if not self._needs_restart.get(app_key):
            return None
        instances = tuple(self.resolve_instance_infos(app_key).values())
        first_failed = next((info for info in instances if is_failed_info(info)), None)
        return AppManifestInfo(
            app_key=app_key,
            class_name=instances[0].class_name,
            display_name=app_key,
            filename="",
            enabled=True,
            status=AppStatus.FAILED,
            instance_count=len(instances),
            instances=instances,
            error_message=first_failed.error_message if first_failed else None,
            error_traceback=first_failed.error_traceback if first_failed else None,
            in_current_config=False,
            needs_restart_count=count_needs_restart(instances),
        )

    @property
    def only_apps(self) -> frozenset[str]:
        """App keys in the exclusive-app filter; empty when no filter is set."""
        return self._only_apps

    @property
    def manifests(self) -> dict[str, "AppManifest"]:
        """All configured app manifests keyed by app key, including disabled ones."""
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
    - If absent (a DB-only / removed app): status defaults to ``AppStatus.STOPPED`` with
      zero instances, and ``in_current_config`` is ``False`` — unless an instance of it is still
      flagged needs-restart, in which case it is FAILED and lists its flagged instances
      (``AppRegistry.build_orphaned_flag_info``).

    Static metadata (``class_name``, ``display_name``, ``filename``, ``autostart``) always
    comes from the DB row, never from the in-memory manifest — the DB is the source of truth
    for metadata, the registry is the source of truth for live status.
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
            "autostart": bool(db_row["autostart"]),
        }

        if in_memory_manifest is not None:
            # Static metadata still comes from the DB row (source of truth for config);
            # the computed runtime fields (status/instances/...) come from `derived`, and
            # `enabled` also comes from `derived` since it drives `derived.status` — keeping
            # both on the same source prevents a stale-DB `enabled` from disagreeing with a
            # freshly-derived `status`.
            derived = registry.build_manifest_info(app_key, in_memory_manifest)
            info = replace(derived, app_key=app_key, in_current_config=True, **static_fields)
        elif (flagged := registry.build_orphaned_flag_info(app_key)) is not None:
            info = replace(flagged, enabled=bool(db_row["enabled"]), **static_fields)
        else:
            info = AppManifestInfo(
                app_key=app_key,
                status=AppStatus.STOPPED,
                enabled=bool(db_row["enabled"]),
                in_current_config=False,
                **static_fields,
            )

        results.append(info)

    return results


def count_needs_restart(instances: Iterable[AppInstanceInfo]) -> int:
    """Number of instance snapshots flagged needs-restart."""
    return sum(1 for info in instances if info.needs_restart is not None)
