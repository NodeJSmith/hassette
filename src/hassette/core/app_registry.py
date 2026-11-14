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
from hassette.utils.exception_utils import get_traceback_string

if TYPE_CHECKING:
    from hassette import AppConfig
    from hassette.app import App
    from hassette.config.classes import AppManifest

UNKNOWN_LABEL = "Unknown"


LIVE_STATUSES = frozenset(
    {ResourceStatus.NOT_STARTED, ResourceStatus.STARTING, ResourceStatus.RUNNING, ResourceStatus.STOPPING}
)
"""Statuses whose entry holds a live ``App``."""

MISSING_ENTRY_STATUSES = frozenset({ResourceStatus.NOT_STARTED, ResourceStatus.FAILED})
"""Statuses ``set_status`` accepts for a name with no entry: registration, and a failure before any ``App`` existed.

A missing entry reads as NOT_STARTED. Any other write to one comes from a late writer racing process exit or a
concurrent stop, and is dropped so it can't create a ghost entry or report a bogus change."""


@dataclass(frozen=True)
class InstanceEntry:
    """One tracked app instance.

    An entry with a live status (``LIVE_STATUSES``) holds its ``App``. A FAILED entry holds none, carries the
    error, and can carry ``needs_restart``. STOPPED is never stored: it removes the entry.

    No ``instance_name`` field: the dict key ``_instances[app_key][instance_name]`` is the single
    source of truth.
    """

    app: "App[AppConfig] | None"
    status: ResourceStatus
    error: Exception | None = None
    error_message: str | None = None
    error_traceback: str | None = None
    needs_restart: NeedsRestartInfo | None = None

    @property
    def holds_app(self) -> bool:
        """Whether this entry holds its ``App`` (any live status), as opposed to a recorded failure."""
        return self.app is not None


@dataclass(frozen=True)
class StatusChange:
    """One app instance status transition, as ``AppRegistry.set_status`` applied it."""

    app_key: str
    instance_name: str
    class_name: str
    previous: ResourceStatus | None
    """The status before the write. Always set by ``set_status``; ``None`` only in events the test harness
    simulates without a known previous status."""
    status: ResourceStatus
    error: Exception | None = None
    needs_restart: NeedsRestartInfo | None = None
    """The entry's needs-restart flag after the write. Only a FAILED change can carry one, since every other
    write onto a flagged entry is refused."""


class AppRegistry:
    """Manages app instance state and provides queryable status interface.

    Single source of truth for app state with snapshot generation for web UI.

    Per-instance state is one ``InstanceEntry`` per instance name, and ``set_status`` is its only writer
    (``clear_all`` aside). Every per-instance reader goes through ``resolve_instance_info`` or
    ``resolve_instance_infos``.

    Position carries no identity here. Display order is derived on each read by ``display_names``.
    """

    def __init__(self) -> None:
        self._instances: dict[str, dict[str, InstanceEntry]] = defaultdict(dict)
        self._blocked_apps: dict[str, BlockReason] = {}
        self._manifests: dict[str, AppManifest] = {}
        self._only_apps: frozenset[str] = frozenset()
        self._debug_capture: set[tuple[str, str]] = set()
        self.logger = getLogger(f"{__name__}.AppRegistry")

    def set_status(
        self,
        app_key: str,
        instance_name: str,
        to: ResourceStatus,
        *,
        app: "App[AppConfig] | None" = None,
        error: Exception | None = None,
        needs_restart: NeedsRestartInfo | None = None,
    ) -> StatusChange | None:
        """Write the status of ``(app_key, instance_name)`` and return the change, or ``None`` when no event is owed.

        The previous status comes from the entry; a missing entry reads as NOT_STARTED. A write is a change
        when the status differs, or when it is FAILED with a different error object (compared by identity).

        - NOT_STARTED registers ``app``, replacing whatever the name held. Onto a missing entry it changes
          nothing, so it returns ``None``.
        - STARTING, RUNNING and STOPPING keep the entry's ``App``.
        - FAILED drops the ``App`` and stores ``error``. ``needs_restart`` flags the entry; the first flag on a
          name stands until ``clear_all``, and a later FAILED write keeps it while replacing the error.
        - STOPPED removes the entry.

        Rejected writes change nothing and return ``None``: any status but NOT_STARTED or FAILED onto a missing
        entry (DEBUG log), a live status onto an entry with no ``App`` (DEBUG log), and anything but FAILED onto
        a flagged entry (WARNING log, since every normal path refuses a flagged name before writing).

        Args:
            app_key: The app key.
            instance_name: The instance name.
            to: The new status.
            app: The instance being registered; required for NOT_STARTED, ignored otherwise.
            error: The failure; required for FAILED, ignored otherwise.
            needs_restart: Flags a FAILED entry needs-restart; ignored for other statuses.
        """
        if to is ResourceStatus.FAILED and error is None:
            raise ValueError("a FAILED write needs an error")
        if to is ResourceStatus.NOT_STARTED and app is None:
            raise ValueError("a NOT_STARTED write needs the app being registered")

        current = self._instances.get(app_key, {}).get(instance_name)
        if current is None and to not in MISSING_ENTRY_STATUSES:
            self.logger.debug("Dropped %s write for untracked app '%s' instance '%s'", to, app_key, instance_name)
            return None
        if current is not None and current.needs_restart is not None and to is not ResourceStatus.FAILED:
            self.logger.warning(
                "Refused %s write for app '%s' instance '%s', flagged needs-restart", to, app_key, instance_name
            )
            return None
        previous_app = current.app if current is not None else None
        if to in LIVE_STATUSES and to is not ResourceStatus.NOT_STARTED and previous_app is None:
            self.logger.debug("Dropped %s write for failed app '%s' instance '%s'", to, app_key, instance_name)
            return None

        previous = current.status if current is not None else ResourceStatus.NOT_STARTED
        previous_error = current.error if current is not None else None
        current_flag = current.needs_restart if current is not None else None
        flag = current_flag or needs_restart
        new_failure = to is ResourceStatus.FAILED and (error is not previous_error or flag is not current_flag)
        is_change = previous is not to or new_failure
        live_app = app if to is ResourceStatus.NOT_STARTED else previous_app

        # The write happens even when it isn't a change: a re-registration replaces the App, and a repeat
        # FAILED write can add the needs-restart flag.
        if to is ResourceStatus.STOPPED:
            self._remove(app_key, instance_name)
        elif to is ResourceStatus.FAILED and error is not None:  # the guard above makes error set for FAILED
            self._instances[app_key][instance_name] = InstanceEntry(
                app=None,
                status=ResourceStatus.FAILED,
                error=error,
                error_message=str(error),
                error_traceback=get_traceback_string(error) if error.__traceback__ else None,
                needs_restart=flag,
            )
        else:
            self._instances[app_key][instance_name] = InstanceEntry(app=live_app, status=to)

        if not is_change:
            return None
        self.logger.debug("App '%s' instance '%s': %s -> %s", app_key, instance_name, previous, to)
        return StatusChange(
            app_key=app_key,
            instance_name=instance_name,
            class_name=self._class_name(app_key, live_app or previous_app),
            previous=previous,
            status=to,
            error=error if to is ResourceStatus.FAILED else None,
            needs_restart=flag if to is ResourceStatus.FAILED else None,
        )

    def _remove(self, app_key: str, instance_name: str) -> None:
        """Remove one entry, and ``app_key``'s map with it once empty, so iteration never sees an empty map."""
        entries = self._instances[app_key]
        del entries[instance_name]
        if not entries:
            del self._instances[app_key]

    def _class_name(self, app_key: str, app: "App[AppConfig] | None") -> str:
        """The class name of an instance: its ``App``'s, else the loaded manifest's, else ``UNKNOWN_LABEL``."""
        if app is not None:
            return app.class_name
        manifest = self._manifests.get(app_key)
        return manifest.class_name if manifest is not None else UNKNOWN_LABEL

    def get_needs_restart(self, app_key: str, instance_name: str) -> NeedsRestartInfo | None:
        """The needs-restart flag of ``(app_key, instance_name)``, or ``None`` when it isn't flagged."""
        entry = self._instances.get(app_key, {}).get(instance_name)
        return entry.needs_restart if entry is not None else None

    def refusal_reason(self, app_key: str, instance_name: str) -> str | None:
        """Why an action is refused on a flagged ``(app_key, instance_name)``, or ``None`` when it isn't flagged.

        The ``reason`` of every refused outcome, so a refusal reads the same on every path. It carries the flag's
        time and reason, which match the ERROR logged when the instance was flagged.

        The gate covers this app key and this name only. A renamed instance, or a name moved to another app key,
        passes it and can start beside the old instance's leftover work, while the old name stays FAILED with its
        reason until restart. For a moved name that leftover work shares an owner id with the new instance, so a
        late teardown can remove the new instance's registrations until hassette restarts.
        """
        info = self.get_needs_restart(app_key, instance_name)
        if info is None:
            return None
        return f"needs a hassette restart (flagged at {info.flagged_at}: {info.reason})"

    def is_debug_captured(self, app_key: str, instance_name: str) -> bool:
        """Whether debug capture is on for ``(app_key, instance_name)``."""
        return (app_key, instance_name) in self._debug_capture

    def set_debug_capture(self, app_key: str, instance_names: Iterable[str], enabled: bool) -> None:
        """Turn debug capture on or off for each of ``instance_names`` under ``app_key``.

        A pair isn't tied to an instance entry, so it survives the entry removal and
        re-registration a reload does. Turning capture off for an uncaptured name is a no-op.
        """
        pairs = {(app_key, name) for name in instance_names}
        if enabled:
            self._debug_capture |= pairs
        else:
            self._debug_capture -= pairs

    def debug_captured_names(self, app_key: str) -> set[str]:
        """Every instance name under ``app_key`` with debug capture on, configured or not."""
        return {name for key, name in self._debug_capture if key == app_key}

    def clear_debug_capture(self, app_key: str) -> None:
        """Turn debug capture off for every name under ``app_key``."""
        self.set_debug_capture(app_key, self.debug_captured_names(app_key), enabled=False)

    def prune_stale_debug_capture(self, app_key: str, configured_names: Iterable[str]) -> None:
        """Drop capture pairs of ``app_key`` whose name left the config and that no live instance holds.

        Nothing else would show or end such a pair: the status read lists configured and tracked names only, and
        the instance route answers 404 for a name outside the config. A running orphan keeps its pair, so the status
        read matches its live levels until it is stopped.
        """
        configured = set(configured_names)
        running = set(self.get_live_apps(app_key))
        stale = {name for name in self.debug_captured_names(app_key) if name not in configured and name not in running}
        self.set_debug_capture(app_key, stale, enabled=False)

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
        entry = self._instances.get(app_key, {}).get(instance_name)
        if entry is None:
            return None
        return self._info_from_entry(app_key, instance_name, entry, manifest or self._manifests.get(app_key))

    def tracked_names(self, app_key: str) -> set[str]:
        """Names with an instance entry for ``app_key``."""
        return set(self._instances.get(app_key, {}))

    def resolve_instance_infos(self, app_key: str, manifest: "AppManifest | None" = None) -> dict[str, AppInstanceInfo]:
        """``resolve_instance_info`` for every tracked name of ``app_key``, in display order."""
        manifest = manifest or self._manifests.get(app_key)
        return {
            name: info
            for name in self.display_names(app_key, manifest)
            if (info := self.resolve_instance_info(app_key, name, manifest)) is not None
        }

    def stale_failed_names(self, app_key: str, configured_names: Iterable[str]) -> list[str]:
        """Names of ``app_key``'s unflagged failure entries that are no longer in the current config.

        Config can drop an instance without the app going through a full reload — e.g. an
        ``autostart=false`` app that isn't auto-reconciled on a config change (see
        ``AppLifecycleService.should_auto_reconcile``) and is later started manually.
        ``AppFactory.create_instances()`` only ever touches configured names, so without pruning, a
        failed entry under a since-removed name lingers in the registry forever, misreporting the
        app as degraded/failed even after it starts cleanly. The caller writes STOPPED for each name, so each
        removal sends its own event. Running entries are left out: an orphaned *running* instance needs an
        actual shutdown, not just a registry removal. Flagged entries are left out too: only ``clear_all``
        removes one.
        """
        configured = set(configured_names)
        return [
            name
            for name, entry in self._instances.get(app_key, {}).items()
            if not entry.holds_app and entry.needs_restart is None and name not in configured
        ]

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
        """Clear all instance entries (flagged ones included), blocked apps and debug capture.

        A raw reset outside ``set_status`` that sends no events. It runs only at process exit (``shutdown_all``)
        and on test reset, after every instance registered when ``shutdown_all`` began has sent its own STOPPED or
        FAILED, so nothing is left that anyone could act on. An instance a runtime start registers after
        ``shutdown_all`` took its list is cleared without an event, since ``shutdown_all`` holds no app-key lock.
        """
        self._instances.clear()
        self._blocked_apps.clear()
        self._debug_capture.clear()

    def set_manifests(self, manifests: dict[str, "AppManifest"]) -> None:
        """Update the app manifests configuration."""
        self._manifests = manifests.copy()

    def set_only_apps(self, app_keys: Iterable[str]) -> None:
        """Set the exclusive-app filter. An empty iterable clears it."""
        self._only_apps = frozenset(app_keys)

    def __contains__(self, app_key: str) -> bool:
        return any(entry.holds_app for entry in self._instances.get(app_key, {}).values())

    def app_keys(self) -> list[str]:
        """Get all app keys with at least one entry holding its ``App`` (any live status)."""
        return [
            app_key
            for app_key, entries in self._instances.items()
            if any(entry.holds_app for entry in entries.values())
        ]

    def flagged_app_keys(self) -> list[str]:
        """Get all app keys with at least one instance flagged needs-restart.

        Retention keeps these apps' manifest rows, so this must cover every removed app ``listed_apps`` keeps.
        """
        return [
            app_key
            for app_key, entries in self._instances.items()
            if any(entry.needs_restart is not None for entry in entries.values())
        ]

    def get(self, app_key: str, instance_name: str | None = None) -> "App[AppConfig] | None":
        """Get an instance's ``App`` by name; with no name, the first one holding an ``App`` in display order."""
        entries = self._instances.get(app_key, {})
        if instance_name is not None:
            entry = entries.get(instance_name)
            return entry.app if entry is not None else None
        running = (entries[name].app for name in self.display_names(app_key) if name in entries)
        return next((app for app in running if app is not None), None)

    def get_status(self, app_key: str, instance_name: str) -> ResourceStatus | None:
        """An instance's stored status, or ``None`` when the registry doesn't track it."""
        entry = self._instances.get(app_key, {}).get(instance_name)
        return entry.status if entry is not None else None

    def get_manifest(self, app_key: str) -> "AppManifest | None":
        """Get the manifest for an app key."""
        return self._manifests.get(app_key)

    def configured_names(self, app_key: str) -> list[str]:
        """The instance names ``app_key``'s config declares, in config order; empty for an unknown app."""
        manifest = self._manifests.get(app_key)
        return configured_instance_names(manifest.app_config) if manifest is not None else []

    def all_apps(self) -> list["App[AppConfig]"]:
        """Get every ``App`` the registry holds, in any live status."""
        return [
            app for entries in self._instances.values() for entry in entries.values() if (app := entry.app) is not None
        ]

    def get_live_apps(self, app_key: str) -> dict[str, "App[AppConfig]"]:
        """Get every instance of an app key that holds its ``App``, in any live status (excludes failed entries)."""
        return {name: app for name, entry in self._instances.get(app_key, {}).items() if (app := entry.app) is not None}

    def get_instances(self, app_key: str) -> dict[str, InstanceEntry]:
        """Get all entries (running and failed) for an app key."""
        return self._instances.get(app_key, {}).copy()

    def _info_from_entry(
        self, app_key: str, instance_name: str, entry: InstanceEntry, manifest: "AppManifest | None" = None
    ) -> AppInstanceInfo:
        in_current_config = name_in_current_config(instance_name, manifest)
        debug_capture = self.is_debug_captured(app_key, instance_name)
        if (app := entry.app) is not None:
            return AppInstanceInfo(
                app_key=app_key,
                instance_name=instance_name,
                class_name=app.class_name,
                status=entry.status,
                owner_id=app.unique_name,
                in_current_config=in_current_config,
                debug_capture=debug_capture,
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
            debug_capture=debug_capture,
            needs_restart=entry.needs_restart,
        )

    def get_snapshot(self) -> AppStatusSnapshot:
        """Generate immutable status snapshot for web UI."""
        instances = [info for app_key in self._instances for info in self.resolve_instance_infos(app_key).values()]

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
        ``stale_failed_names``) is still included too: this is a union of tracked and configured
        names (``display_names``), so a live orphan is never dropped from view.

        ``status`` (RUNNING/FAILED/DEGRADED/STOPPED/...) is derived from tracked names only
        (instance entries, through ``resolve_instance_info``) — a
        configured-but-not-yet-started app is correctly STOPPED, not DEGRADED, even though
        ``instances`` also lists its not-yet-tracked instances. A flagged name counts as failed.
        """
        tracked = self.resolve_instance_infos(app_key, manifest)
        # The frontend's ``appLiveStatus`` (frontend/src/utils/app-data.ts) mirrors this rollup rule (#4147).
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
                    debug_capture=self.is_debug_captured(app_key, name),
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
        """Runtime fields for an app absent from the loaded config that still has an instance flagged needs-restart.

        Returns ``None`` when no instance of the app is flagged. A flagged entry is tracked, so ``instances`` is
        never empty past the guard. With no manifest, the class name reads ``UNKNOWN_LABEL``.

        ``display_name``, ``filename`` and ``enabled`` are placeholders: static metadata is the caller's
        to fill in (``overlay_runtime_state`` overrides them from the DB row).
        """
        if not any(entry.needs_restart is not None for entry in self._instances.get(app_key, {}).values()):
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

    Static metadata (``class_name``, ``display_name``, ``description``, ``filename``, ``autostart``) always
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
            "description": db_row["description"],
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
