"""AppChangeReconcilerMixin — file-watcher and config-change detection and reconciliation."""

import asyncio
import typing
from collections.abc import Awaitable, Callable, Iterable
from copy import deepcopy
from dataclasses import dataclass, replace
from logging import Logger
from pathlib import Path

from pydantic import ValidationError

import hassette.event_handling.accessors as A
from hassette.core.app_change_detector import ChangeSet
from hassette.core.app_lifecycle_common import (
    ActionOutcomes,
    ManualReload,
    ReconcileTrigger,
    WatcherTrigger,
    log_refusals,
)
from hassette.events.hassette import HassetteSimpleEvent
from hassette.exceptions import (
    AppBlockedError,
    AppBootstrapNotReleasedError,
    AppRemovedError,
    ConfigError,
    ReloadBusyError,
    ReloadConfigInvalidError,
    ReloadSyntaxError,
)
from hassette.schemas.app_config_shape import configs_by_name, configured_instance_names
from hassette.schemas.app_outcomes import OutcomeResult, ReloadAllResult
from hassette.types import Topic
from hassette.utils.app_modules import app_roots, describe_syntax_error, evict_apps_package, precheck_apps_package
from hassette.utils.exception_utils import get_short_traceback

if typing.TYPE_CHECKING:
    from hassette import Hassette, HassetteConfig
    from hassette.config.classes import AppManifest
    from hassette.core.app_bootstrap_coordinator import AppBootstrapCoordinator
    from hassette.core.app_change_detector import AppChangeDetector
    from hassette.core.app_factory import AppFactory
    from hassette.core.app_key_lock import AppKeyLock
    from hassette.core.app_lifecycle_common import PendingReconciliation
    from hassette.core.app_registry import AppRegistry
    from hassette.schemas.app_outcomes import InstanceOutcome


NO_ROOTS: frozenset[Path] = frozenset()
"""No app roots: a reconcile that isn't a reload-all evicts nothing."""


@dataclass(frozen=True)
class AppRestart:
    """One app's part of a config or file change: which of its instances to stop and recreate."""

    app_key: str
    names: tuple[str, ...] | None = None
    """The instance names to touch, or None for every instance of the app. Each one is stopped if tracked, and
    created if still configured, so a removed name is only stopped and an added one only created."""
    force_reload: bool = False
    """Re-import the app class from disk, if its file changed, before recreating. Only set with ``names=None``:
    a re-import always restarts every instance."""


class AppChangeReconcilerMixin:
    """File-watcher and config-change detection and reconciliation for ``AppLifecycleService``."""

    # Provided by the AppLifecycleService host (its own body, Resource, or a sibling mixin);
    # declared here for type narrowing within the mixin.
    hassette: "Hassette"
    logger: Logger
    registry: "AppRegistry"
    factory: "AppFactory"
    change_detector: "AppChangeDetector"
    bootstrap_coordinator: "AppBootstrapCoordinator"
    _change_event_lock: "AppKeyLock"
    _pending_reconciliation: "PendingReconciliation | None"
    _get_app_key_lock: Callable[[str], "AppKeyLock"]
    _resolve_manifest: Callable[[str], "AppManifest | None"]
    _record_pre_release_reconciliation: Callable[..., None]
    _take_pre_release_reconciliation: Callable[
        [], tuple[dict[str, "AppManifest"] | None, dict[str, "AppManifest"] | None, frozenset[Path]]
    ]
    should_autostart: Callable[[str], bool]
    should_auto_reconcile: Callable[[str], bool]
    start_app: Callable[..., Awaitable[tuple["InstanceOutcome", ...]]]
    _start_app_unlocked: Callable[..., Awaitable[None]]
    _stop_app_unlocked: Callable[..., Awaitable[None]]
    _stop_targets: Callable[[str], set[str]]
    _prune_stopped_debug_capture: Callable[[str], None]
    _outcomes_for: Callable[[str, Iterable[str]], ActionOutcomes]
    _instance_in_config: Callable[[str, str, "AppManifest"], bool]
    _create_instance_unlocked: Callable[..., Awaitable[None]]
    _stop_instance_unlocked: Callable[..., Awaitable[None]]
    persist_manifests: Callable[[], Awaitable[None]]
    set_apps_configs: Callable[[dict[str, "AppManifest"]], None]
    resolve_only_apps: Callable[[], Awaitable[None]]
    _fold_unblocked_apps_into_changes: Callable[[ChangeSet], ChangeSet]

    async def apply_changes(
        self,
        changes: ChangeSet,
        original_config: dict[str, "AppManifest"],
        current_config: dict[str, "AppManifest"],
        *,
        adopt: "Callable[[ChangeSet], Awaitable[ChangeSet]] | None" = None,
        fail_fast: bool = False,
        evict_roots: frozenset[Path] = NO_ROOTS,
        log_refused: bool = True,
    ) -> ReloadAllResult:
        """Apply detected changes by stopping, reloading, or starting apps, and return what each app's did.

        Precondition: the four change buckets are disjoint, as guaranteed by
        ``AppChangeDetector.detect_changes`` (orphans are keys absent from the
        current config; reimport/reload/new are all keys present in it). Callers constructing a ``ChangeSet``
        by hand (e.g. tests) must keep the buckets disjoint.

        The lock of every orphan, reimport and reload key is taken first, in sorted order, each exactly once.
        Then ``adopt`` commits the new config, the orphans stop, every restart stops, the app-code modules are
        evicted (``changes.reload_all`` only), every restart's replacements are created, and the new apps start,
        each ``start_app`` taking its own key's lock.

        Args:
            changes: The set of changes to apply
            original_config: The app manifests before this change (used to diff per-instance
                ``app_config`` entries for the ``reload_apps`` bucket — see below)
            current_config: The app manifests after this change
            adopt: Commits the change's config once every lock is held, returning the change set with any
                newly-unblocked apps folded in. None when the config is already committed.
            fail_fast: Raise ``ReloadBusyError`` at the first key another action holds or waits for, after
                releasing the locks already taken, instead of waiting for it.
            evict_roots: The app roots to evict under when ``changes.reload_all`` is set: the old config's and
                the new one's, so modules loaded from a root the change removed are evicted too.
            log_refused: Log each refused instance, for a caller with no response to carry the refusals.

        Raises:
            ReloadBusyError: ``fail_fast`` and a key is busy. Nothing was done.
        """
        self.logger.debug("Applying app changes: %s", changes)
        held = await self._take_key_locks(
            sorted(changes.orphans | changes.reimport_apps | changes.reload_apps), fail_fast
        )
        outcomes: dict[str, tuple[InstanceOutcome, ...]] = {}
        try:
            if adopt is not None:
                changes = await adopt(changes)

            for app_key in sorted(changes.orphans):
                self.logger.debug("Stopping orphaned app %s", app_key)
                outcomes[app_key] = await self._stop_orphan_unlocked(app_key)
            if changes.orphans:
                self._queue_retire_unconfigured_instances()

            # Each key is decided under its own lock: the decision reads registry state that a stop holding the
            # lock could change. A key with nothing to restart releases its lock as soon as it is decided.
            tracked = set(self.registry.tracked_app_keys()) if changes.reload_all else set()
            restarts: list[AppRestart] = []
            for app_key in sorted(changes.reimport_apps | changes.reload_apps):
                restart = self._decide_restart(
                    app_key,
                    original_config,
                    current_config,
                    reimport=app_key in changes.reimport_apps,
                    tracked=app_key in tracked,
                )
                if restart is None:
                    self._get_app_key_lock(app_key).release()
                    held.remove(app_key)
                else:
                    restarts.append(restart)

            restart_outcomes = await self._stop_restarts_unlocked(restarts)
            if changes.reload_all:
                evicted = evict_apps_package(evict_roots)
                self.logger.debug("Evicted %d app-code module(s): %s", len(evicted), evicted)
            outcomes.update(await self._create_restarts_unlocked(restarts, restart_outcomes))
        finally:
            for app_key in reversed(held):
                self._get_app_key_lock(app_key).release()

        # AppBlockedError from start_app() below is caught per app_key, even though it should be structurally
        # unreachable here: AppChangeDetector.detect_changes() filters every ChangeSet bucket by only_apps
        # before this method ever sees app_key, and _fold_unblocked_apps_into_changes() only adds apps that were
        # *just* unblocked. That invariant spans three files and isn't enforced at this boundary, so if it's
        # ever violated, an uncaught raise here would abort every app after the blocked one.
        for app_key in sorted(changes.new_apps):
            if not self.should_autostart(app_key):
                self.logger.debug("Skipping autostart of app %s (autostart=false)", app_key)
                continue

            self.logger.debug("Starting new app %s", app_key)
            try:
                outcomes[app_key] = await self.start_app(app_key)
            except AppBlockedError:
                self.logger.error("Skipping start of blocked app %s — this should not be reachable", app_key)
            except AppRemovedError:
                self.logger.debug("Skipping start of app %s: its manifest is gone", app_key)

        if log_refused:
            for app_key, app_outcomes in outcomes.items():
                log_refusals(self.logger, app_key, app_outcomes)
        return ReloadAllResult(apps=outcomes)

    async def _take_key_locks(self, app_keys: list[str], fail_fast: bool) -> list[str]:
        """Take each key's lock in the given (sorted) order, and return the keys taken.

        Under ``fail_fast`` each key's ``busy`` is tested in the same synchronous step as its take: an
        uncontended ``AppKeyLock`` is acquired without suspending, so no other task can claim it in between. A busy
        key releases the locks already taken and raises. A cancellation while waiting releases them too.

        Raises:
            ReloadBusyError: ``fail_fast`` and a key is busy.
        """
        taken: list[str] = []
        try:
            for app_key in app_keys:
                lock = self._get_app_key_lock(app_key)
                if fail_fast and lock.busy:
                    raise ReloadBusyError(f"Another action on app {app_key!r} is still running", app_key=app_key)
                await lock.acquire()
                taken.append(app_key)
        except BaseException:
            for app_key in reversed(taken):
                self._get_app_key_lock(app_key).release()
            raise
        return taken

    async def _stop_orphan_unlocked(self, app_key: str) -> "tuple[InstanceOutcome, ...]":
        """Stop every instance of an app the new config removed or disabled. Caller must hold its key's lock."""
        outcomes = self._outcomes_for(app_key, self._stop_targets(app_key))
        try:
            await self._stop_app_unlocked(app_key, outcomes=outcomes)
            self._prune_stopped_debug_capture(app_key)
        finally:
            # Its debug routes now answer 404, so nothing could end a capture left behind (spec 148 D8),
            # including on an instance the stop failed to remove or a stop cancelled partway. Instances the
            # stop did remove were already reset by ``shutdown_instance``; this covers the ones still here.
            for survivor in self.registry.get_live_apps(app_key).values():
                survivor.set_debug_capture(False)
            self.registry.clear_debug_capture(app_key)
        return outcomes.finish()

    def _decide_restart(
        self,
        app_key: str,
        original_config: dict[str, "AppManifest"],
        current_config: dict[str, "AppManifest"],
        *,
        reimport: bool,
        tracked: bool = False,
    ) -> "AppRestart | None":
        """Decide what one reimported or reloaded key needs: a restart, or None for nothing.

        ``reimport`` is True for a key in ``reimport_apps`` and False for one in ``reload_apps``; the two buckets
        are disjoint (``AppChangeDetector.detect_changes``). ``tracked`` is True for a key a reload-all restarts
        because it has an instance entry, live or FAILED: it restarts as a full reimport whatever its autostart
        says, so an app that failed on the old code recovers. Caller must hold the key's lock.
        """
        if tracked:
            return AppRestart(app_key, force_reload=True)
        if not self._should_restart(app_key):
            return None
        if reimport:
            return AppRestart(app_key, force_reload=True)
        return self._plan_reload(app_key, original_config, current_config)

    def _should_restart(self, app_key: str) -> bool:
        if self.should_auto_reconcile(app_key):
            return True
        self.logger.debug("Skipping restart of autostart=false app %s (not running)", app_key)
        return False

    def _plan_reload(
        self,
        app_key: str,
        original_config: dict[str, "AppManifest"],
        current_config: dict[str, "AppManifest"],
    ) -> "AppRestart | None":
        """Plan the restart a config change needs, or return None when no instance changed.

        Instances compare by name, so moving a block restarts nothing, and a rename is one stop and
        one create. The plan covers the names only in the old config, the names only in the new one,
        and the names in both whose ``app_config`` dict changed. It covers every instance when the app
        has none running (dormant) or a manifest is missing on either side.

        A dormant app (no running instances) that reaches here via should_auto_reconcile
        (autostart just flipped to True) needs all instances created, not just the changed ones,
        or its unchanged siblings would stay unstarted.
        """
        old_manifest = original_config.get(app_key)
        new_manifest = current_config.get(app_key)
        if app_key not in self.registry or old_manifest is None or new_manifest is None:
            return AppRestart(app_key)

        old_instances = configs_by_name(old_manifest.app_config)
        new_instances = configs_by_name(new_manifest.app_config)
        changed = tuple(
            name
            for name in old_instances | new_instances
            if name not in old_instances or name not in new_instances or old_instances[name] != new_instances[name]
        )
        if not changed:
            self.logger.debug("No per-instance config changes detected for app %s", app_key)
            return None
        return AppRestart(app_key, names=changed)

    async def _stop_restarts_unlocked(self, restarts: list["AppRestart"]) -> dict[str, ActionOutcomes]:
        """Stop every instance the restarts replace; the first half of a restart, before any replacement exists.

        Bus/Scheduler owner registries are keyed by instance name, and a config change can hand a
        name from one instance to another, within one app or across apps (``a`` -> ``b`` while
        another instance goes ``b`` -> ``c``). Creating any replacement while the old holder of its
        name is still running would let the old one's teardown remove the new one's registrations,
        so nothing is created until everything being replaced has stopped. A reload-all evicts the app-code
        modules between the two halves, so no stopped instance imports the new code during its teardown.

        Caller must hold the app-key lock of every restart's key (``asyncio.Lock`` is not reentrant).

        A name that left the config is gone once its stop ends, but its listeners stay active until something
        retires them, so the sweep's retire step is queued right after the stops. It runs on the database's write
        queue, which the reload doesn't wait on; if it is dropped, the next retention cycle retires them.

        Returns:
            Each restart's outcomes so far, by app key, for ``_create_restarts_unlocked`` to finish.
        """
        outcomes = {
            restart.app_key: self._outcomes_for(
                restart.app_key,
                self._stop_targets(restart.app_key) if restart.names is None else restart.names,
            )
            for restart in restarts
        }
        for restart in restarts:
            await self._stop_for_restart(restart, outcomes[restart.app_key])
        if any(self._stopped_name_left_config(restart.app_key, outcomes[restart.app_key]) for restart in restarts):
            self._queue_retire_unconfigured_instances()
        return outcomes

    async def _create_restarts_unlocked(
        self, restarts: list["AppRestart"], outcomes: dict[str, ActionOutcomes]
    ) -> "dict[str, tuple[InstanceOutcome, ...]]":
        """Create every restart's replacements, the second half after ``_stop_restarts_unlocked``.

        Caller must hold the app-key lock of every restart's key.

        Returns:
            Each restart's final per-instance outcomes, by app key.
        """
        for restart in restarts:
            await self._start_for_restart(restart, outcomes[restart.app_key])
        return {restart.app_key: outcomes[restart.app_key].finish() for restart in restarts}

    def _queue_retire_unconfigured_instances(self) -> None:
        """Ask the database to retire removed names' rows now, leaving a dropped request to the hourly sweep."""
        try:
            database = self.hassette.database_service
        except RuntimeError:
            # The accessor raises only when no DatabaseService is wired (a test harness); there are no rows to retire.
            self.logger.debug("DatabaseService not wired; no removed instance's rows to retire")
            return
        if not database.enqueue_retire_unconfigured_instances():
            self.logger.warning(
                "Dropped the queued retire of removed instances' rows; the next retention cycle does it"
            )

    def _stopped_name_left_config(self, app_key: str, outcomes: ActionOutcomes) -> bool:
        """Whether a restart's stop half targeted a name its app's current config doesn't have."""
        manifest = self.registry.get_manifest(app_key)
        configured = configured_instance_names(manifest.app_config) if manifest is not None else []
        return not set(outcomes.names).issubset(configured)

    async def _stop_for_restart(self, restart: "AppRestart", outcomes: ActionOutcomes) -> None:
        # Both stop bodies catch and log their own failures, so one app's failed stop can't abort the batch.
        if restart.names is None:
            self.logger.debug("Stopping app %s for reload", restart.app_key)
            await self._stop_app_unlocked(restart.app_key, outcomes=outcomes)
            return
        self.logger.debug("Stopping changed instance(s) %s of app %s", list(restart.names), restart.app_key)
        await asyncio.gather(
            *(self._stop_instance_unlocked(restart.app_key, name, outcomes=outcomes) for name in restart.names)
        )

    async def _start_for_restart(self, restart: "AppRestart", outcomes: ActionOutcomes) -> None:
        # AppRestart carries only the key and names, so the manifest is read from the registry here.
        app_key = restart.app_key
        app_manifest = self._resolve_manifest(app_key)
        if not app_manifest:
            self.logger.warning("App %s has no manifest any more; not restarting it", app_key)
            return

        if restart.names is None:
            outcomes.begin_create_half(configured_instance_names(app_manifest.app_config))
            try:
                await self._start_app_unlocked(app_key, app_manifest, restart.force_reload, outcomes=outcomes)
            except AppBlockedError:
                self.logger.error("Skipping reload of blocked app %s — this should not be reachable", app_key)
            except Exception:
                self.logger.error("Failed to reload app %s:\n%s", app_key, get_short_traceback())
            return

        async def create_one(name: str) -> None:
            # A failure of one instance must not abort the other instances, or the other apps in the batch.
            try:
                await self._create_instance_unlocked(app_key, name, app_manifest, outcomes=outcomes)
            except Exception:
                self.logger.error("Failed to reload instance %s of app %s:\n%s", name, app_key, get_short_traceback())

        valid = [name for name in restart.names if self._instance_in_config(app_key, name, app_manifest)]
        outcomes.begin_create_half(valid)
        await asyncio.gather(*(create_one(name) for name in valid))

    async def handle_change_event(
        self,
        changed_file_paths: typing.Annotated[frozenset[Path], A.get_path("payload.data.changed_file_paths")],
    ) -> None:
        """Handle changes detected by the file watcher, through ``reconcile_from_disk``.

        Called as a Bus event handler with DI-injected ``changed_file_paths``. This listener runs in the bus's
        ``parallel`` execution mode (framework tier), so two events dispatched close together are serialized by
        ``reconcile_from_disk``'s reconcile lock rather than by the bus.
        """
        await self.reconcile_from_disk(WatcherTrigger(changed_file_paths))

    async def reconcile_from_disk(self, trigger: ReconcileTrigger) -> ReloadAllResult:
        """Re-read the config and app files from disk and bring the running apps in line with them.

        The one entry point for a file-watcher event and a manual reload-all. In order (spec 162 D12):

        0. Take the reconcile lock. A manual call that mustn't wait refuses if it's busy.
        1. A manual call before bootstrap release refuses. A watcher event defers, as before release always.
        2. Build a candidate config, committing nothing. An invalid one refuses a manual call; a watcher
           event logs it and reconciles against the current config with no reload-all.
        3. Detect the changes, deciding ``reload_all``: forced for a manual call, from the changed paths for a
           watcher event. A reload-all runs the syntax precheck first, which refuses a manual call; a watcher
           event logs it and drops only the reload-all part.
        4. ``apply_changes``: take the restart and orphan locks, adopt the candidate, stop, evict, create, and
           start the new apps.

        Every refusal comes before anything is committed or stopped.

        Returns:
            What the reconcile did to each app; empty when it found nothing to apply.

        Raises:
            ReloadBusyError: A manual call with ``wait`` false found another reload, or an action on an app it
                restarts, running.
            AppBootstrapNotReleasedError: A manual call before bootstrap release.
            ReloadConfigInvalidError: A manual call found the config on disk invalid.
            ReloadSyntaxError: A manual call found a syntax error in a file it would import.
        """
        manual = isinstance(trigger, ManualReload)
        fail_fast = manual and not trigger.wait
        if fail_fast and self._change_event_lock.busy:
            raise ReloadBusyError("Another reload is still running")
        async with self._change_event_lock:
            if manual and not self.bootstrap_coordinator.is_released():
                raise AppBootstrapNotReleasedError("Apps cannot be reloaded before bootstrap release")

            original_apps_config = {k: deepcopy(v) for k, v in self.registry.manifests.items()}
            old_roots = app_roots(self.hassette.config)
            candidate = self._build_candidate(raise_invalid=manual)
            if candidate is not None:
                current_apps_config = {k: deepcopy(v) for k, v in candidate.apps.manifests.items()}
            else:
                current_apps_config = {k: deepcopy(v) for k, v in original_apps_config.items()}
            changed_file_paths = trigger.paths if isinstance(trigger, WatcherTrigger) else frozenset()

            if not self.bootstrap_coordinator.is_released():
                # Only a watcher event gets here (step 1). No app has started, so there is nothing to lock: commit
                # the config now and defer the lifecycle work, as before release always has.
                await self._defer_pre_release_change(candidate, original_apps_config, changed_file_paths)
                return ReloadAllResult()

            if self._pending_reconciliation is not None:
                # A pre-release change is still queued. Fold it into this diff's baseline so the
                # comparison spans everything since before release, then clear the queue — otherwise
                # bootstrap's later replay would apply that stale snapshot on top of a config it no
                # longer matches.
                self.logger.debug("Merging queued pre-release reconciliation into post-release change")
                pending_original, _, pending_paths = self._take_pre_release_reconciliation()
                if pending_original is not None:
                    original_apps_config = pending_original
                    changed_file_paths |= pending_paths

            new_roots = app_roots(candidate) if candidate is not None else None
            only_apps = frozenset((candidate or self.hassette.config).only_apps)
            changes = self.change_detector.detect_changes(
                original_apps_config,
                current_apps_config,
                changed_file_paths,
                only_apps=only_apps,
                app_roots=new_roots if not manual else None,
                force_reload_all=manual,
            )
            if changes.reload_all and new_roots is not None:
                changes = self._precheck_reload_all(changes, current_apps_config, new_roots, raise_refusal=manual)
            if changes.reload_all:
                changes = self._with_tracked_restarts(changes, current_apps_config, only_apps)

            if not changes.has_changes:
                changes = await self._adopt(candidate, changes)
                if not changes.has_any_change:
                    self.logger.debug("%s changed but no app changes detected", changed_file_paths)
                    return ReloadAllResult()
                adopt = None
            else:
                adopt = self._adopter(candidate)

            self.logger.debug("%s changed, app changes detected - %s", changed_file_paths, changes)
            result = await self._reconcile_changes(
                changes,
                original_apps_config,
                current_apps_config,
                adopt=adopt,
                fail_fast=fail_fast,
                evict_roots=old_roots | (new_roots or frozenset()),
                log_refused=not manual,
            )
            if changes.reload_all and not manual:  # the web route logs a manual reload-all's summary, with its source
                self.logger.info(
                    "File-watcher reload-all finished for %d app(s): %d succeeded, %d failed, %d refused",
                    len(result.apps),
                    result.count(OutcomeResult.SUCCEEDED),
                    result.count(OutcomeResult.FAILED),
                    result.count(OutcomeResult.REFUSED),
                )
            return result

    def _build_candidate(self, *, raise_invalid: bool) -> "HassetteConfig | None":
        """Build a candidate config from disk without committing it; None when it is invalid and not raised.

        Raises:
            ReloadConfigInvalidError: ``raise_invalid`` and the config on disk is invalid.
        """
        try:
            return self.hassette.config.build_reload_candidate()
        except Exception as exc:  # an invalid config on disk (ConfigError) needs no traceback; a bug does
            if raise_invalid:
                raise ReloadConfigInvalidError(f"The configuration is invalid: {config_error_summary(exc)}") from exc
            self.logger.error("Config reload rejected: %s", exc, exc_info=not isinstance(exc, ConfigError))
            return None

    def _precheck_reload_all(
        self,
        changes: ChangeSet,
        current_config: dict[str, "AppManifest"],
        roots: frozenset[Path],
        *,
        raise_refusal: bool,
    ) -> ChangeSet:
        """Compile every file the reload-all would import; on a syntax error, refuse or drop the reload-all.

        Raises:
            ReloadSyntaxError: ``raise_refusal`` and a file has a syntax error.
        """
        enabled_files = [manifest.full_path for manifest in current_config.values() if manifest.enabled]
        error = precheck_apps_package(roots, enabled_files)
        if error is None:
            return changes
        detail = describe_syntax_error(error, roots)
        if raise_refusal:
            raise ReloadSyntaxError(detail)
        self.logger.error("Reload-all refused, nothing was stopped: %s", detail)
        return replace(changes, reload_all=False)

    def _with_tracked_restarts(
        self, changes: ChangeSet, current_config: dict[str, "AppManifest"], only_apps: frozenset[str]
    ) -> ChangeSet:
        """Add every tracked app key the new config still runs to the reimports (spec 162 D1).

        A key with any instance entry, live or FAILED, restarts; one with none (someone stopped it) doesn't. A key
        the new config removes, disables or blocks with ``--app`` is left to the other buckets.
        """
        running = {
            key for key, manifest in current_config.items() if manifest.enabled and (not only_apps or key in only_apps)
        }
        tracked = (set(self.registry.tracked_app_keys()) & running) - changes.new_apps - changes.orphans
        return replace(
            changes,
            reimport_apps=changes.reimport_apps | tracked,
            reload_apps=changes.reload_apps - tracked,
        )

    def _adopter(self, candidate: "HassetteConfig | None") -> "Callable[[ChangeSet], Awaitable[ChangeSet]]":
        """``_adopt`` bound to ``candidate``, for ``apply_changes`` to run once it holds every lock."""

        async def adopt(changes: ChangeSet) -> ChangeSet:
            return await self._adopt(candidate, changes)

        return adopt

    async def _adopt(self, candidate: "HassetteConfig | None", changes: ChangeSet) -> ChangeSet:
        """Commit ``candidate``, reconcile the blocked state, and fold any newly-unblocked apps into ``changes``."""
        await self._commit_candidate(candidate)
        return self._fold_unblocked_apps_into_changes(changes)

    async def _commit_candidate(self, candidate: "HassetteConfig | None") -> None:
        """Swap in ``candidate``, set the registry's manifests and ``--app`` filter, and persist the manifests.

        None (an invalid config on disk) keeps the current config and commits nothing.
        """
        if candidate is None:
            return
        self.hassette.config.adopt(candidate)
        self.set_apps_configs(self.hassette.config.apps.manifests)
        # Restore the --app filter before the persist await, so status reads never see it cleared.
        await self.resolve_only_apps()
        await self.persist_manifests()

    async def _defer_pre_release_change(
        self,
        candidate: "HassetteConfig | None",
        original_apps_config: dict[str, "AppManifest"],
        changed_file_paths: frozenset[Path],
    ) -> None:
        """Commit a pre-release watcher change's config, and queue its lifecycle work for bootstrap's replay."""
        await self._commit_candidate(candidate)
        current_apps_config = {k: deepcopy(v) for k, v in self.registry.manifests.items()}
        changes = self._fold_unblocked_apps_into_changes(
            self.change_detector.detect_changes(
                original_apps_config, current_apps_config, changed_file_paths, only_apps=self.registry.only_apps
            )
        )
        if not changes.has_any_change:
            self.logger.debug("%s changed but no app changes detected", changed_file_paths)
            return
        if changes.has_changes:
            self.logger.debug("Deferring app reconciliation until bootstrap release opens")
            self._record_pre_release_reconciliation(
                original_apps_config=original_apps_config,
                current_apps_config=current_apps_config,
                changed_file_paths=changed_file_paths,
            )
            return
        # A metadata-only change (e.g. display_name) has nothing for apply_changes()
        # to redo later, so there's no reconciliation to defer. But WebApiService can
        # already be serving manifests to a connected dashboard before bootstrap
        # release opens (see RuntimeQueryService.depends_on, which excludes
        # AppHandler), and release may not open for a long time -- or at all -- while
        # Home Assistant is unreachable. Broadcast now via _reconcile_changes(), which
        # skips apply_changes() since changes.has_changes is False here.
        self.logger.debug("%s changed (metadata-only) before bootstrap release opened", changed_file_paths)
        await self._reconcile_changes(changes, original_apps_config, current_apps_config)

    async def _replay_pre_release_reconciliation_if_needed(self) -> bool:
        """Replay a deferred pre-release reconciliation, if one is queued.

        Returns:
            True if a queued reconciliation was replayed and broadcast a manifest-refetch
            signal via ``_reconcile_changes`` -- callers that send their own unconditional
            "bootstrap finished" broadcast afterward should skip it when this returns True,
            or the same signal goes out twice for one bootstrap pass.
        """
        # Shares _pending_reconciliation state with handle_change_event(), which serializes on
        # this same lock — without it, a file-watcher event arriving as bootstrap replays could
        # race the take/clear of that state.
        async with self._change_event_lock:
            if self._pending_reconciliation is None:
                return False

            original_apps_config, current_apps_config, changed_file_paths = self._take_pre_release_reconciliation()
            if original_apps_config is None or current_apps_config is None:
                return False
            self.logger.debug("Replaying deferred app reconciliation after bootstrap release opens")
            await self.resolve_only_apps()

            changes = self.change_detector.detect_changes(
                original_apps_config, current_apps_config, changed_file_paths, only_apps=self.registry.only_apps
            )

            changes = self._fold_unblocked_apps_into_changes(changes)

            if not changes.has_any_change:
                self.logger.debug("Deferred app reconciliation produced no changes")
                return False

            await self._reconcile_changes(changes, original_apps_config, current_apps_config)
            return True

    async def _reconcile_changes(
        self,
        changes: ChangeSet,
        original_config: dict[str, "AppManifest"],
        current_config: dict[str, "AppManifest"],
        *,
        adopt: "Callable[[ChangeSet], Awaitable[ChangeSet]] | None" = None,
        fail_fast: bool = False,
        evict_roots: frozenset[Path] = NO_ROOTS,
        log_refused: bool = True,
    ) -> ReloadAllResult:
        """Apply a non-empty ``ChangeSet`` and broadcast a manifest-refetch signal.

        The single place ``reconcile_from_disk()`` and
        ``_replay_pre_release_reconciliation_if_needed()`` route every ``ChangeSet``-driven
        apply-then-broadcast decision through, rather than hand-rolling it at each call site's
        own terminal branch -- a new branch that calls ``apply_changes()``/``send_event()``
        directly instead of through here risks reintroducing the class of gap where one branch
        applies changes (or persists metadata) but forgets to broadcast. Callers must already
        have confirmed ``changes.has_any_change`` before calling. This is distinct from
        ``bootstrap_apps()``'s own unconditional "bootstrap sequence finished" broadcast, which
        isn't driven by a ``ChangeSet`` and stays a direct ``send_event()`` call there.

        The keyword arguments pass through to ``apply_changes``.
        """
        result = ReloadAllResult()
        if changes.has_changes:
            result = await self.apply_changes(
                changes,
                original_config,
                current_config,
                adopt=adopt,
                fail_fast=fail_fast,
                evict_roots=evict_roots,
                log_refused=log_refused,
            )

        await self.hassette.send_event(
            HassetteSimpleEvent.from_topic(topic=Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED),
        )
        return result


def config_error_summary(exc: Exception) -> str:
    """An invalid config's errors as ``location: message`` parts, leaving out the rejected values.

    A refusal's message reaches the web API, and a rejected value can be a secret (a mistyped token, say), so a
    validation error is reduced to where and why. Any other error keeps its message.
    """
    cause = exc.__cause__
    if not isinstance(cause, ValidationError):
        return str(exc)
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or '(root)'}: {error['msg']}" for error in cause.errors()
    )
