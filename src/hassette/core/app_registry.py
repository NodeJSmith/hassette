"""App registry for tracking app state with queryable interface."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace
from logging import getLogger
from typing import TYPE_CHECKING, Any

from hassette_wire import AppStatus, ResourceStatus

from hassette.schemas.app_config_shape import configured_instance_names
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

    No ``instance_name`` field: the dict key ``_instances[app_key][instance_name]`` is the single
    source of truth.
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
    """A needs-restart flag on one ``(app_key, instance_name)``, kept outside the instance map.

    Stores the class name so the row still renders after its entry is unregistered or its app leaves config.
    """

    class_name: str
    info: NeedsRestartInfo


class AppRegistry:
    """Manages app instance state and provides queryable status interface.

    Single source of truth for app state with snapshot generation for web UI.

    Per-instance state is keyed by instance name, and has two parts: the instance entry (running or failed)
    and an optional needs-restart record. ``_combine_instance_info`` is the one place they combine; every
    per-instance reader goes through it, by way of ``resolve_instance_info`` or ``resolve_instance_infos``.

    Position carries no identity here. Display order is derived on each read by ``display_names``.
    """

    def __init__(self) -> None:
        self._instances: dict[str, dict[str, InstanceEntry]] = defaultdict(dict)
        self._needs_restart: dict[str, dict[str, NeedsRestartRecord]] = defaultdict(dict)
        self._blocked_apps: dict[str, BlockReason] = {}
        self._manifests: dict[str, AppManifest] = {}
        self._only_apps: frozenset[str] = frozenset()
        self.logger = getLogger(f"{__name__}.AppRegistry")

    def register_app(self, app_key: str, app: "App[AppConfig]") -> None:
        """Register a running app instance under its own ``instance_name``, replacing any prior entry under it."""
        self._instances[app_key][app.instance_name] = InstanceEntry(app=app, status=ResourceStatus.RUNNING)
        self.logger.debug("Registered app '%s' instance '%s'", app_key, app.instance_name)

    def unregister_app(self, app_key: str, instance_name: str | None = None) -> dict[str, "App[AppConfig]"] | None:
        """Remove app instance(s). Returns removed running instances (failed entries are discarded)."""
        if instance_name is None:
            entries = self._instances.pop(app_key, None)
            if entries is None:
                return None
            return {name: app for name, entry in entries.items() if (app := entry.app) is not None}

        if app_key not in self._instances:
            return None

        entry = self._instances[app_key].pop(instance_name, None)

        if not self._instances[app_key]:
            del self._instances[app_key]

        if entry is not None and (app := entry.app) is not None:
            return {instance_name: app}

        return None

    def record_failure(self, app_key: str, instance_name: str, error: Exception) -> None:
        """Record a failed app startup/crash, replacing any prior entry under that name."""
        self.logger.debug("Recording failure for app '%s' instance '%s': %s", app_key, instance_name, error)
        self._instances[app_key][instance_name] = InstanceEntry(
            app=None,
            status=ResourceStatus.FAILED,
            error=error,
            error_message=str(error),
            error_traceback=get_traceback_string(error) if error.__traceback__ else None,
        )

    def flag_needs_restart(
        self,
        app_key: str,
        instance_name: str,
        *,
        class_name: str,
        reason: str,
        pending_tasks: Iterable[str] = (),
    ) -> bool:
        """Record that ``(app_key, instance_name)`` needs a hassette restart because work may still be running.

        The first record under a name stands until restart: a later flag on the same name is not merged
        in, and returns ``False``. Survives ``unregister_app``, ``record_failure`` and config changes;
        only ``clear_all`` (process exit, test reset) removes it.

        Returns:
            ``True`` when this call created the record.
        """
        records = self._needs_restart[app_key]
        if instance_name in records:
            return False
        records[instance_name] = NeedsRestartRecord(
            class_name=class_name,
            info=NeedsRestartInfo(reason=reason, pending_tasks=tuple(pending_tasks), flagged_at=date_utils.now()),
        )
        self.logger.debug("Flagged app '%s' instance '%s' needs restart: %s", app_key, instance_name, reason)
        return True

    def get_needs_restart(self, app_key: str, instance_name: str) -> NeedsRestartRecord | None:
        """The needs-restart record of ``(app_key, instance_name)``, or ``None`` when it isn't flagged."""
        return self._needs_restart.get(app_key, {}).get(instance_name)

    def refusal_reason(self, app_key: str, instance_name: str) -> str | None:
        """Why an action is refused on a flagged ``(app_key, instance_name)``, or ``None`` when it isn't flagged.

        The ``reason`` of every refused outcome, so a refusal reads the same on every path. It carries the flag's
        time and reason, which match the ERROR logged when the instance was flagged.

        The gate covers this app key and this name only. A renamed instance, or a name moved to another app key,
        passes it and can start beside the old instance's leftover work, while the old name stays FAILED with its
        reason until restart. For a moved name that leftover work shares an owner id with the new instance, so a
        late teardown can remove the new instance's registrations until hassette restarts.
        """
        record = self.get_needs_restart(app_key, instance_name)
        if record is None:
            return None
        return f"needs a hassette restart (flagged at {record.info.flagged_at}: {record.info.reason})"

    def display_names(self, app_key: str, manifest: "AppManifest | None" = None) -> list[str]:
        """Each name of ``app_key``, in display order.

        Configured names come first, in config order, then names still tracked outside the config (orphans),
        sorted by name. Derived on each read, so the order can shift when the config changes.

        ``manifest`` defaults to the loaded manifest for ``app_key``.
        """
        manifest = manifest or self._manifests.get(app_key)
        configured = configured_instance_names(manifest.app_config) if manifest is not None else []
        orphans = sorted(self.tracked_names(app_key).difference(configured))
        return [*configured, *orphans]

    def resolve_instance_info(
        self, app_key: str, instance_name: str, manifest: "AppManifest | None" = None
    ) -> AppInstanceInfo | None:
        """The effective snapshot of one ``(app_key, instance_name)``, or ``None`` when nothing is tracked there.

        ``manifest`` classifies the instance; it defaults to the loaded manifest for ``app_key``.
        """
        return self._combine_instance_info(app_key, instance_name, manifest or self._manifests.get(app_key))

    def _combine_instance_info(
        self, app_key: str, instance_name: str, manifest: "AppManifest | None"
    ) -> AppInstanceInfo | None:
        """Combine an instance entry and its needs-restart record, the one place the two meet.

        A record wins whatever the entry says: the result is FAILED with ``needs_restart`` set, and when the entry
        holds no error message the record's reason serves as it. Without a record, the result is the entry's.
        """
        entry = self._instances.get(app_key, {}).get(instance_name)
        record = self.get_needs_restart(app_key, instance_name)
        if record is None:
            return self._info_from_entry(app_key, instance_name, entry, manifest) if entry is not None else None

        if entry is not None:
            base = self._info_from_entry(app_key, instance_name, entry, manifest)
        else:
            base = AppInstanceInfo(
                app_key=app_key,
                instance_name=instance_name,
                class_name=record.class_name,
                status=ResourceStatus.FAILED,
                in_current_config=name_in_current_config(instance_name, manifest),
            )
        return replace(
            base,
            status=ResourceStatus.FAILED,
            error_message=base.error_message or record.info.reason,
            needs_restart=record.info,
        )

    def tracked_names(self, app_key: str) -> set[str]:
        """Names with an instance entry or a needs-restart record for ``app_key``."""
        return set(self._instances.get(app_key, {})) | set(self._needs_restart.get(app_key, {}))

    def resolve_instance_infos(self, app_key: str, manifest: "AppManifest | None" = None) -> dict[str, AppInstanceInfo]:
        """``resolve_instance_info`` for every tracked name of ``app_key``, in display order."""
        manifest = manifest or self._manifests.get(app_key)
        return {
            name: info
            for name in self.display_names(app_key, manifest)
            if (info := self._combine_instance_info(app_key, name, manifest)) is not None
        }

    def prune_stale_failed(self, app_key: str, configured_names: Iterable[str]) -> dict[str, AppInstanceInfo]:
        """Remove failed (non-running) entries whose name is no longer in the current config.

        Returns what was removed, resolved to ``AppInstanceInfo`` (same as ``get_failed_instance_infos``).
        A needs-restart record under a pruned name is kept, so its resolved snapshot stays FAILED.

        Config can drop an instance without the app going through a full reload — e.g. an
        ``autostart=false`` app that isn't auto-reconciled on a config change (see
        ``AppLifecycleService.should_auto_reconcile``) and is later started manually.
        ``AppFactory.create_instances()`` only ever touches configured names, so without this, a
        failed entry under a since-removed name lingers in the registry forever, misreporting the
        app as degraded/failed even after it starts cleanly. Running entries are untouched — an
        orphaned *running* instance needs an actual shutdown, not just a registry removal, which is
        out of scope here.

        The return value lets the caller emit a status-change event for each removed entry —
        callers must not discard entries silently (see ``AppLifecycleService._stop_app_unlocked``
        for why: the WS status cache never learns otherwise, and stays on FAILED forever).
        """
        entries = self._instances.get(app_key)
        if not entries:
            return {}
        configured = set(configured_names)
        stale_names = [name for name, entry in entries.items() if not entry.is_running and name not in configured]
        pruned = {name: info for name in stale_names if (info := self.resolve_instance_info(app_key, name))}
        for name in stale_names:
            del entries[name]
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
        ``AppLifecycleService`` — a blocked app's manifest still exists (and still configures
        its instances), so it stays addressable by configured-name and
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

    def get(self, app_key: str, instance_name: str | None = None) -> "App[AppConfig] | None":
        """Get a running app instance by name; with no name, the first running one in display order."""
        entries = self._instances.get(app_key, {})
        if instance_name is not None:
            entry = entries.get(instance_name)
            return entry.app if entry is not None else None
        running = (entries[name].app for name in self.display_names(app_key) if name in entries)
        return next((app for app in running if app is not None), None)

    def get_manifest(self, app_key: str) -> "AppManifest | None":
        """Get the manifest for an app key."""
        return self._manifests.get(app_key)

    def all_apps(self) -> list["App[AppConfig]"]:
        """Get all running app instances."""
        return [
            app for entries in self._instances.values() for entry in entries.values() if (app := entry.app) is not None
        ]

    def get_running_apps(self, app_key: str) -> dict[str, "App[AppConfig]"]:
        """Get all running instances for an app key (excludes failed entries)."""
        return {name: app for name, entry in self._instances.get(app_key, {}).items() if (app := entry.app) is not None}

    def get_instances(self, app_key: str) -> dict[str, InstanceEntry]:
        """Get all entries (running and failed) for an app key."""
        return self._instances.get(app_key, {}).copy()

    def get_failed_instance_infos(self, app_key: str) -> dict[str, AppInstanceInfo]:
        """Get resolved AppInstanceInfo for failed instances of an app key: failed entries and flagged names.

        Used to emit a status-change event for failures recorded by ``AppFactory.create_instances()``
        before an ``App`` object existed to build the event from — reuses the same class_name
        resolution as snapshot generation so the event matches what a subsequent fetch would show.
        """
        return {name: info for name, info in self.resolve_instance_infos(app_key).items() if is_failed_info(info)}

    def _info_from_entry(
        self, app_key: str, instance_name: str, entry: InstanceEntry, manifest: "AppManifest | None" = None
    ) -> AppInstanceInfo:
        in_current_config = name_in_current_config(instance_name, manifest)
        if (app := entry.app) is not None:
            return AppInstanceInfo(
                app_key=app_key,
                instance_name=instance_name,
                class_name=app.class_name,
                status=app.status,
                owner_id=app.unique_name,
                in_current_config=in_current_config,
            )

        class_name = manifest.class_name if manifest else UNKNOWN_LABEL
        return AppInstanceInfo(
            app_key=app_key,
            instance_name=instance_name,
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

        A configured name with no registry entry (never started, or independently stopped via
        ``AppLifecycleService.stop_instance()``) gets a synthetic ``ResourceStatus.STOPPED``
        placeholder so it stays addressable by the CLI and visible in the web UI instead of
        silently disappearing from ``instances`` once its instance is no longer tracked. A
        tracked name outside the current config (an orphaned running instance after a removal — see
        ``prune_stale_failed``) is still included too: this is a union of tracked and configured
        names (``display_names``), so a live orphan is never dropped from view.

        ``status`` (RUNNING/FAILED/DEGRADED/STOPPED/...) is derived from tracked names only
        (entries and needs-restart records, through ``resolve_instance_info``) — a
        configured-but-not-yet-started app is correctly STOPPED, not DEGRADED, even though
        ``instances`` also lists its not-yet-tracked instances. A flagged name counts as failed.
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

        instances: list[AppInstanceInfo] = []
        error_message: str | None = None
        error_traceback: str | None = None

        for name in self.display_names(app_key, manifest):
            info = tracked.get(name)
            if info is not None:
                if is_failed_info(info) and error_message is None:
                    error_message = info.error_message
                    error_traceback = info.error_traceback
            else:
                info = AppInstanceInfo(
                    app_key=app_key,
                    instance_name=name,
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

        Returns ``None`` when the app has no record. A record makes its name tracked, and the resolver
        returns an info for every flagged name, so ``instances`` is never empty past the guard.

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


def listed_apps(infos: Iterable[AppManifestInfo]) -> list[AppManifestInfo]:
    """The apps an app list shows: every configured app, and a removed one only while an instance is flagged.

    A removed app's ``app_manifests`` row outlives it until its history ages out of retention
    (``build_prune_removed_app_manifests_query``), and ``overlay_runtime_state`` reports such a row as
    STOPPED. Lists leave it out so it never reads as a stopped app; ``GET /apps/{app_key}`` still
    answers for it. A removed app with a flagged needs-restart instance stays listed, as FAILED, because
    that instance's work may still be running.
    """
    # A removed app's snapshot lists instances only through build_orphaned_flag_info, i.e. flagged ones.
    return [info for info in infos if info.in_current_config or info.instances]


def name_in_current_config(instance_name: str, manifest: "AppManifest | None") -> bool:
    """Whether ``manifest`` configures ``instance_name``.

    Without a manifest there are no configured names to compare against; the app-level
    ``AppManifestInfo.in_current_config`` covers a wholly orphaned app.
    """
    return manifest is None or instance_name in configured_instance_names(manifest.app_config)


def count_needs_restart(instances: Iterable[AppInstanceInfo]) -> int:
    """Number of instance snapshots flagged needs-restart."""
    return sum(1 for info in instances if info.needs_restart is not None)
