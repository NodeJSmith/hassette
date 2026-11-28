"""AppChangeApplierMixin — applies a reconcile: stops, evicts, recreates and starts the apps it names.

``app_lifecycle_reconcile`` (``reconcile_from_disk``) plans the reconcile: the ``ChangeSet`` and any reload-all.
Each app's restart decision (``_decide_restart``) is made here, because it needs the app's lock held.
"""

import asyncio
import typing
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from logging import Logger
from pathlib import Path

from hassette.core.app_change_detector import ChangeSet
from hassette.core.app_lifecycle_common import ActionOutcomes, ReloadAllPlan, log_refusals
from hassette.exceptions import AppBlockedError, AppRemovedError, ReloadBusyError
from hassette.schemas.app_config_shape import configs_by_name, configured_instance_names
from hassette.schemas.app_outcomes import AppResult, ReconcileAction, ReconcileResult
from hassette.utils.app_modules import evict_apps_package
from hassette.utils.exception_utils import get_short_traceback

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.config.classes import AppManifest
    from hassette.core.app_key_lock import AppKeyLock
    from hassette.core.app_registry import AppRegistry
    from hassette.schemas.app_outcomes import InstanceOutcome


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


class AppChangeApplierMixin:
    """Applies a reconcile's ``ChangeSet`` and reload-all plan for ``AppLifecycleService``."""

    # Provided by the AppLifecycleService host (its own body, Resource, or a sibling mixin);
    # declared here for type narrowing within the mixin.
    hassette: "Hassette"
    logger: Logger
    registry: "AppRegistry"
    _get_app_key_lock: Callable[[str], "AppKeyLock"]
    _resolve_manifest: Callable[[str], "AppManifest | None"]
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

    # dup-ignore-start: every hop of apply_changes takes the same (changes, original, current) config parameters
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
        # dup-ignore-end
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

    # dup-ignore-start: every hop of apply_changes takes the same (changes, original, current) config parameters
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
        # dup-ignore-end
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
