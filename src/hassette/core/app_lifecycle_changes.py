"""AppChangeReconcilerMixin — file-watcher and config-change detection and reconciliation."""

import asyncio
import functools
import sys
import time
import typing
from collections.abc import Awaitable, Callable, Iterable
from copy import deepcopy
from dataclasses import dataclass
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
from hassette.schemas.app_outcomes import AppResult, OutcomeResult, ReconcileAction, ReconcileResult
from hassette.types import Topic
from hassette.utils.app_modules import (
    app_roots,
    describe_syntax_error,
    evict_apps_package,
    needs_reload_all,
    precheck_apps_package,
)
from hassette.utils.exception_utils import get_short_traceback, validation_error_summary

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


@dataclass(frozen=True)
class ReloadAllPlan:
    """A reload-all: evict every app-code module under ``evict_roots``, and restart ``restart_keys`` on the new code.

    ``reconcile_from_disk`` builds it once a manual call or a watcher change needs one and the syntax precheck
    passed; a reconcile without one evicts nothing and restarts only the apps its ``ChangeSet`` names.
    """

    restart_keys: frozenset[str]
    """Every key the new config still runs that had an instance entry, live or FAILED, or an action in flight
    when the reload-all was planned (spec 162 D1). Each restarts as a full re-import, whatever its autostart says,
    if it is still tracked once its lock is held."""
    evict_roots: frozenset[Path]
    """The old config's app roots and the new one's, so modules loaded from a root the change removed go too."""


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
    _reconcile_lock: "AppKeyLock"
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
        reload_all: ReloadAllPlan | None = None,
        adopt: "Callable[[ChangeSet], Awaitable[ChangeSet]] | None" = None,
        fail_fast: bool = False,
        log_refused: bool = True,
    ) -> ReconcileResult:
        """Apply detected changes by stopping, reloading, or starting apps, and return what each app's did.

        Precondition: the orphan, new, reimport and reload buckets are disjoint, as guaranteed by
        ``AppChangeDetector.detect_changes`` (orphans are keys absent from the current config; reimport/reload/new
        are all keys present in it). Callers constructing a ``ChangeSet`` by hand (e.g. tests) must keep that shape.

        The lock of every orphan, reimport, reload and reload-all restart key is taken first, in sorted order, each
        exactly once. Then ``adopt`` commits the new config, the orphans stop, every restart stops, the app-code
        modules are evicted (``reload_all`` only), every restart's replacements are created, and the new apps start,
        each ``start_app`` taking its own key's lock.

        Args:
            changes: The set of changes to apply
            original_config: The app manifests before this change, diffed per instance against
                ``current_config`` to decide which instances a ``reload_apps`` key restarts (``_plan_reload``)
            current_config: The app manifests after this change
            reload_all: The reload-all to run with these changes, or None for none.
            adopt: Commits the change's config once every lock is held, returning the change set with any
                newly-unblocked apps folded in. None when the config is already committed.
            fail_fast: Raise ``ReloadBusyError`` at the first key another action holds or waits for, after
                releasing the locks already taken, instead of waiting for it.
            log_refused: Log each refused instance, for a caller with no response to carry the refusals.

        Raises:
            ReloadBusyError: ``fail_fast`` and a key is busy. Nothing was done.
        """
        self.logger.debug("Applying app changes: %s (reload-all: %s)", changes, reload_all)
        reload_all_keys = reload_all.restart_keys if reload_all is not None else frozenset()
        restart_keys = changes.reimport_apps | changes.reload_apps | reload_all_keys
        held = await self._take_key_locks(sorted(changes.orphans | restart_keys), fail_fast)
        results: dict[str, AppResult] = {}
        try:
            if adopt is not None:
                changes = await adopt(changes)

            for app_key in sorted(changes.orphans):
                self.logger.debug("Stopping orphaned app %s", app_key)
                results[app_key] = AppResult(ReconcileAction.STOP, await self._stop_orphan_unlocked(app_key))
            if changes.orphans:
                self._queue_retire_unconfigured_instances()

            # Each key is decided under its own lock: the decision reads registry state that a stop holding the
            # lock could change. A key with nothing to restart releases its lock as soon as it is decided.
            still_tracked = set(self.registry.tracked_app_keys())
            restarts: list[AppRestart] = []
            for app_key in sorted(restart_keys):
                restart = self._decide_restart(
                    app_key,
                    changes,
                    original_config,
                    current_config,
                    in_reload_all=app_key in reload_all_keys,
                    still_tracked=app_key in still_tracked,
                )
                if restart is None:
                    self._get_app_key_lock(app_key).release()
                    held.remove(app_key)
                else:
                    restarts.append(restart)

            restart_outcomes = await self._stop_restarts_unlocked(restarts)
            if reload_all is not None:
                self._evict_app_code(reload_all.evict_roots)
            for app_key, outcomes in (await self._create_restarts_unlocked(restarts, restart_outcomes)).items():
                results[app_key] = AppResult(ReconcileAction.RELOAD, outcomes)
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
                results[app_key] = AppResult(ReconcileAction.START, await self.start_app(app_key))
            except AppBlockedError:
                self.logger.error("Skipping start of blocked app %s — this should not be reachable", app_key)
            except AppRemovedError:
                self.logger.debug("Skipping start of app %s: its manifest is gone", app_key)

        if log_refused:
            for app_key, result in results.items():
                log_refusals(self.logger, app_key, result.outcomes)
        return ReconcileResult(apps=results)

    def _evict_app_code(self, roots: frozenset[Path]) -> None:
        """Evict the app-code modules between a reload-all's stops and its creates.

        A failure is logged and the creates still run: the apps come back, some possibly on modules the eviction
        missed, rather than every restarted app staying stopped.
        """
        try:
            evicted = evict_apps_package(roots)
        except Exception:
            self.logger.exception("Evicting the app-code modules failed; apps restart, some possibly on old code")
            return
        self.logger.debug("Evicted %d app-code module(s): %s", len(evicted), evicted)

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
                    raise ReloadBusyError(f"Another action on app {app_key!r} is still running")
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
        changes: ChangeSet,
        original_config: dict[str, "AppManifest"],
        current_config: dict[str, "AppManifest"],
        *,
        in_reload_all: bool,
        still_tracked: bool,
    ) -> "AppRestart | None":
        """Decide what one restart key needs: a restart, or None for nothing. Caller must hold the key's lock.

        A reload-all restart key restarts as a full reimport whatever its autostart says, so an app that failed on the
        old code recovers, but only while it still has an instance entry now that its lock is held (spec 162 D1). One
        without an entry (stopped by hand, or its in-flight action was a stop) stays stopped, unless its own file
        changed: that follows the watcher's reimport rule, as it would without the reload-all. Every other key follows
        the watcher's rules.

        Args:
            app_key: The key to decide.
            changes: The reconcile's change set.
            original_config: The app manifests before the change.
            current_config: The app manifests after the change.
            in_reload_all: Whether ``app_key`` is one of the reload-all's restart keys.
            still_tracked: Whether ``app_key`` has an instance entry now that its lock is held.
        """
        if in_reload_all:
            if still_tracked:
                return AppRestart(app_key, force_reload=True)
            if app_key not in changes.reimport_apps:
                # A config reload alone would restart it through the watcher's autostart rule.
                self.logger.debug("Not restarting app %s for the reload-all: it has no instance entry", app_key)
                return None
        elif app_key not in changes.reimport_apps and app_key not in changes.reload_apps:
            return None
        if not self._should_restart(app_key):
            return None
        if app_key in changes.reimport_apps:
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
        return bool(set(outcomes.names) - set(configured))

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

    async def reconcile_from_disk(self, trigger: ReconcileTrigger) -> ReconcileResult:
        """Re-read the config and app files from disk and bring the running apps in line with them.

        The one entry point for a file-watcher event and a manual reload-all. In order (spec 162 D12):

        0. Take the reconcile lock. A manual call that mustn't wait refuses if it's busy.
        1. A manual call before bootstrap release refuses. A watcher event before release commits the config and
           queues its lifecycle work for bootstrap's replay.
        2. Build a candidate config, committing nothing. An invalid one refuses a manual call; a watcher
           event logs it and reconciles against the current config with no reload-all.
        3. Detect the changes, then plan the reload-all (``_plan_reload_all``): always for a manual call, from the
           changed paths for a watcher event. A reload-all runs the syntax precheck first, which refuses a manual
           call; a watcher event logs it and drops only the reload-all part.
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
        started = time.perf_counter()
        manual = isinstance(trigger, ManualReload)
        fail_fast = manual and not trigger.wait
        if fail_fast and self._reconcile_lock.busy:
            raise ReloadBusyError("Another reload is still running")
        async with self._reconcile_lock:
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
                # the config now and queue the lifecycle work for bootstrap's replay.
                await self._defer_pre_release_change(candidate, original_apps_config, changed_file_paths)
                return ReconcileResult()

            pending = self._pending_reconciliation
            if pending is not None:
                # A pre-release change is still queued. Fold it into this diff's baseline so the comparison spans
                # everything since before release. The queue is cleared only when this reconcile commits (``_adopt``),
                # so a refusal leaves it for bootstrap's replay; otherwise the replay would apply that stale snapshot
                # on top of a config it no longer matches.
                self.logger.debug("Merging queued pre-release reconciliation into post-release change")
                original_apps_config = pending.original_apps_config
                changed_file_paths |= pending.changed_paths

            new_roots = app_roots(candidate) if candidate is not None else None
            only_apps = frozenset((candidate if candidate is not None else self.hassette.config).only_apps)
            changes = self.change_detector.detect_changes(
                original_apps_config, current_apps_config, changed_file_paths, only_apps=only_apps
            )
            reload_all = None
            if new_roots is not None:  # a watcher event with an invalid config on disk runs no reload-all
                reload_all = await self._plan_reload_all(
                    current_apps_config,
                    changed_file_paths,
                    manual=manual,
                    old_roots=old_roots,
                    new_roots=new_roots,
                    excluded=changes.new_apps | changes.orphans,
                    only_apps=only_apps,
                )

            adopt = functools.partial(self._adopt, candidate, clear_pending=pending is not None)
            if not changes.has_changes and reload_all is None:
                # Nothing to stop or start, so no lock is needed: commit now. Folding in newly-unblocked apps can
                # still turn this into a change with lifecycle work, applied below on the committed config.
                changes = await adopt(changes)
                if not changes.has_any_change:
                    self.logger.debug("%s changed but no app changes detected", changed_file_paths)
                    return ReconcileResult()
                adopt = None

            self.logger.debug("%s changed, app changes detected - %s", changed_file_paths, changes)
            result = await self._reconcile_changes(
                changes,
                original_apps_config,
                current_apps_config,
                reload_all=reload_all,
                adopt=adopt,
                fail_fast=fail_fast,
                log_refused=not manual,
            )
            if reload_all is not None and not manual:  # the web route logs a manual reload-all's summary
                duration_s = time.perf_counter() - started
                self.logger.info(
                    "File-watcher reload-all finished for %d app(s) in %.1fs: %d succeeded, %d failed, %d refused",
                    len(result.apps),
                    duration_s,
                    result.count(OutcomeResult.SUCCEEDED),
                    result.count(OutcomeResult.FAILED),
                    result.count(OutcomeResult.REFUSED),
                    extra={"duration_s": duration_s},
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

    async def _plan_reload_all(
        self,
        current_config: dict[str, "AppManifest"],
        changed_paths: frozenset[Path],
        *,
        manual: bool,
        old_roots: frozenset[Path],
        new_roots: frozenset[Path],
        excluded: frozenset[str],
        only_apps: frozenset[str],
    ) -> ReloadAllPlan | None:
        """Decide whether this reconcile runs a reload-all, and plan it; None when it doesn't.

        A manual call always plans one. A watcher event plans one when a changed path needs it
        (``needs_reload_all``, spec 162 D4). Either way the syntax precheck runs first. Both scans read and parse
        files, so they run in a worker thread over a snapshot of ``sys.modules`` taken here, leaving the event loop
        free for the HA connection.

        Args:
            current_config: The app manifests the reload-all runs on.
            changed_paths: The paths the watcher reported; empty for a manual call.
            manual: Whether this is a manual reload-all, which refuses where a watcher event logs and drops it.
            old_roots: The running config's resolved app roots; evicted under too, for an ``app_dir`` the edit removed.
            new_roots: The new config's resolved app roots, which the scans read.
            excluded: Keys the other buckets already handle (new and orphaned apps), never reload-all restarts.
            only_apps: The ``--app`` filter; a key it blocks is not restarted.

        Raises:
            ReloadSyntaxError: ``manual`` and a file the reload-all would import has a syntax error.
        """
        modules = dict(sys.modules)
        if not manual:
            app_files = [manifest.full_path for manifest in current_config.values()]
            if not await asyncio.to_thread(needs_reload_all, changed_paths, app_files, new_roots, modules):
                return None
        enabled_files = [manifest.full_path for manifest in current_config.values() if manifest.enabled]
        error = await asyncio.to_thread(precheck_apps_package, new_roots, enabled_files, modules)
        if error is not None:
            detail = describe_syntax_error(error, new_roots)
            if manual:
                raise ReloadSyntaxError(detail)
            self.logger.error(
                "Reload-all cancelled, so no app restarts for it; apps whose own file changed still reload: %s", detail
            )
            return None
        return ReloadAllPlan(
            restart_keys=self._reload_all_restart_keys(current_config, excluded, only_apps),
            evict_roots=old_roots | new_roots,
        )

    def _reload_all_restart_keys(
        self, current_config: dict[str, "AppManifest"], excluded: frozenset[str], only_apps: frozenset[str]
    ) -> frozenset[str]:
        """Every key the new config runs that is tracked or has an action in flight (spec 162 D1).

        A key with any instance entry, live or FAILED, restarts; one with none (someone stopped it) doesn't. A key
        whose lock is held or awaited is included too, so a start already under way finishes before the eviction and
        is restarted onto the new code, not left on the old one. ``_decide_restart`` rechecks tracking once the lock
        is held, so a key whose in-flight action was a stop stays stopped. A key the new config removes, disables or
        blocks with ``--app`` is left to the other buckets.
        """
        runnable = {
            key for key, manifest in current_config.items() if manifest.enabled and (not only_apps or key in only_apps)
        }
        busy = {key for key in runnable if self._get_app_key_lock(key).busy}
        tracked = set(self.registry.tracked_app_keys()) | busy
        return frozenset((tracked & runnable) - excluded)

    async def _adopt(
        self, candidate: "HassetteConfig | None", changes: ChangeSet, *, clear_pending: bool = False
    ) -> ChangeSet:
        """Commit ``candidate``, reconcile the blocked state, and fold any newly-unblocked apps into ``changes``.

        ``clear_pending`` also clears the queued pre-release reconciliation this reconcile folded into its diff.
        """
        if clear_pending:
            self._take_pre_release_reconciliation()
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
        async with self._reconcile_lock:
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
        reload_all: ReloadAllPlan | None = None,
        adopt: "Callable[[ChangeSet], Awaitable[ChangeSet]] | None" = None,
        fail_fast: bool = False,
        log_refused: bool = True,
    ) -> ReconcileResult:
        """Apply a non-empty ``ChangeSet`` (or a reload-all) and broadcast a manifest-refetch signal.

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
        result = ReconcileResult()
        if changes.has_changes or reload_all is not None:
            result = await self.apply_changes(
                changes,
                original_config,
                current_config,
                reload_all=reload_all,
                adopt=adopt,
                fail_fast=fail_fast,
                log_refused=log_refused,
            )

        await self.hassette.send_event(
            HassetteSimpleEvent.from_topic(topic=Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED),
        )
        return result


def config_error_summary(exc: Exception) -> str:
    """An invalid config's errors as ``location: message`` parts, leaving out the rejected values.

    A refusal's message reaches the web API, so a validation error is reduced to where and why
    (``validation_error_summary``). Any other error keeps its message.
    """
    cause = exc.__cause__
    if not isinstance(cause, ValidationError):
        return str(exc)
    return validation_error_summary(cause.errors())
