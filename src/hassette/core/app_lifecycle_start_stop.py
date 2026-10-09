"""AppStartStopMixin — app-level and instance-level start/stop/reload."""

import typing
from collections.abc import Awaitable, Callable
from logging import Logger

from hassette.core.app_lifecycle_common import (
    NOT_STARTED,
    STOPPED,
    AppAdmissionMode,
)
from hassette.events.hassette import HassetteAppStateEvent
from hassette.exceptions import (
    AppBlockedError,
    InvalidInheritanceError,
    UndefinedUserConfigError,
)
from hassette.utils.exception_utils import get_short_traceback

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.config.classes import AppManifest
    from hassette.core.app_factory import AppFactory
    from hassette.core.app_key_lock import AppKeyLock
    from hassette.core.app_registry import AppRegistry
    from hassette.schemas.app_snapshots import AppInstanceInfo


class AppStartStopMixin:
    """App-level and instance-level start/stop/reload for ``AppLifecycleService``."""

    # Provided by the AppLifecycleService host (its own body, Resource, or a sibling mixin);
    # declared here for type narrowing within the mixin.
    hassette: "Hassette"
    logger: Logger
    registry: "AppRegistry"
    factory: "AppFactory"
    _admit_start: Callable[..., Awaitable[None]]
    _get_app_key_lock: Callable[[str], "AppKeyLock"]
    _resolve_manifest: Callable[[str], "AppManifest | None"]
    initialize_instances: Callable[..., Awaitable[None]]
    cleanup_failed_instance: Callable[..., Awaitable[None]]
    shutdown_instances: Callable[..., Awaitable[None]]

    async def start_app(
        self,
        app_key: str,
        force_reload: bool = False,
        *,
        admission_mode: AppAdmissionMode = AppAdmissionMode.REJECT_IF_UNRELEASED,
    ) -> None:
        """Create instances for an app and await their initialization.

        No-ops for any index that already has a live registry entry — calling start on an
        already-running app does not recreate its instances. ``force_reload`` is likewise
        ignored whenever any instance of this app_key is already running, since reloading the
        shared class out from under a live instance would leave it and any newly-created
        sibling on two different class versions. Use ``reload_app()`` to stop-then-recreate
        with a fresh class.

        Args:
            app_key: The app key to start
            force_reload: Whether to force-reload the app class from disk
        """
        app_manifest = self._resolve_manifest(app_key)
        if not app_manifest:
            return

        await self._admit_start(app_key=app_key, admission_mode=admission_mode)

        async with self._get_app_key_lock(app_key):
            # Re-fetch under the lock: _admit_start() can block indefinitely (WAIT_FOR_RELEASE
            # awaits AppBootstrapCoordinator's release latch), and a concurrent file-watcher
            # reconciliation can remove or replace this app's manifest while that wait is
            # parked. Acting on the pre-wait manifest would create instances for an app that
            # no longer exists (or no longer matches current config).
            app_manifest = self._resolve_manifest(app_key)
            if not app_manifest:
                return

            await self._start_app_unlocked(app_key, app_manifest, force_reload)

    async def _start_app_unlocked(self, app_key: str, app_manifest: "AppManifest", force_reload: bool) -> None:
        """Create instances for an app and await their initialization.

        Caller must hold ``self._get_app_key_lock(app_key)``. Extracted from ``start_app`` so
        ``reload_app`` can acquire the app-key lock once and call both the stop and start bodies
        without deadlocking on the non-reentrant ``asyncio.Lock`` (calling the public,
        lock-acquiring `start_app`/`stop_app` from inside an already-held lock would hang).
        """
        if self.registry.is_blocked(app_key):
            # A blocked app's manifest still exists and still reports a configured instance
            # count, so it stays addressable by every check above this one — this is the only
            # thing standing between a manual start/reload and bypassing the exclusive-app
            # filter that blocked it in the first place. Raises (rather than a silent no-op,
            # like the sibling guards above) so the web route and CLI surface an actionable
            # rejection instead of reporting success for a request nothing acted on; start_app()
            # has no surrounding try/except so this propagates directly, and reload_app() special-
            # cases this exception to re-raise past its otherwise-swallowing try/except.
            raise AppBlockedError(f"App {app_key!r} is blocked by the --app filter")

        # A prior, larger config can leave failed entries at indices the *current* config no
        # longer has — e.g. an autostart=false app that wasn't auto-reconciled on the config
        # change (see should_auto_reconcile) and is now being started manually. Prune those
        # before create_instances() runs (not inside it), so pruning applies uniformly whether
        # or not class-loading itself fails, and so pruned entries can be reported as STOPPED —
        # unregister_app()-style silent discarding leaves the WS status cache for that index
        # stuck on FAILED forever (see _stop_app_unlocked for the same problem on the stop side).
        # A no-op on the reload_app() path: _stop_app_unlocked() already popped every entry for
        # app_key (running and failed alike) before this runs, so there's nothing left to prune.
        # This only ever does real work for a standalone start_app() call.
        valid_index_count = len(self.factory.normalize_configs(app_manifest.app_config))
        await self._emit_stopped_events(self.registry.prune_stale_failed_indices(app_key, valid_index_count))

        try:
            self.logger.debug("Creating instances for app %s", app_key)
            created_indices = self.factory.create_instances(app_key, app_manifest, force_reload=force_reload)
        except (UndefinedUserConfigError, InvalidInheritanceError):
            self.logger.error(
                "Failed to load app '%s' due to bad configuration - check previous logs for details", app_key
            )
            return
        except Exception:
            self.logger.error("Failed to load app class for '%s':\n%s", app_key, get_short_traceback())
            return

        # create_instances() records failures (invalid instance_name, config validation, class
        # load error) straight to the registry without emitting an event — no App object exists
        # yet to build one from. Without this, those failures never reach app_status_changed
        # subscribers, so a WS-cached status from before this call (e.g. still "stopped" from a
        # reload's stop phase, or never-set on a first start) lingers indefinitely instead of
        # reflecting the failure — for both a plain start_app() and a reload_app().
        #
        # This re-syncs *every* currently-failed index still within the current config's range,
        # not just ones create_instances() touched on this call (it only overwrites the indices
        # it actually processes — e.g. a class-load failure records index 0 and returns
        # immediately, leaving any pre-existing failures at other in-range indices as-is). A
        # repeated start_app() on an app with untouched stale failures will re-broadcast them
        # unchanged. Accepted: the frontend applies this as a plain state overwrite with no
        # notification side effect (see updateAppStatus in state/store.ts), so a re-broadcast of
        # an already-known status is a harmless no-op, not user-visible noise. Indices *outside*
        # the current config's range don't hit this path at all — those are pruned above instead.
        for info in self.registry.get_failed_instance_infos(app_key).values():
            await self.hassette.send_event(HassetteAppStateEvent.from_instance_info(info))

        # Pass all running instances so reconciliation sees every live listener/job ID.
        # only_indices restricts which instances actually run on_initialize() — pre-existing
        # ones are skipped but still contribute to the reconciliation's live-ID set, preventing
        # their telemetry rows from being retired.
        instances = self.registry.get_running_apps(app_key)
        if instances:
            for idx, inst in instances.items():
                if idx in created_indices:
                    event = HassetteAppStateEvent.from_app(app=inst, status=NOT_STARTED)
                    await self.hassette.send_event(event)
            await self.initialize_instances(app_key, instances, app_manifest, only_indices=created_indices)

    async def _emit_stopped_events(self, infos: "dict[int, AppInstanceInfo]") -> None:
        """Emit a STOPPED event for each given failed-entry snapshot.

        Shared by ``_start_app_unlocked`` (entries pruned for being outside the current config's
        range) and ``_stop_app_unlocked`` (entries silently discarded by ``unregister_app``) —
        both remove a failed entry from the registry without an App object to build an event
        from, and both need the WS status cache to learn the entry is gone rather than staying
        stuck on FAILED forever.
        """
        for info in infos.values():
            await self.hassette.send_event(
                HassetteAppStateEvent.from_instance_info(info, status=STOPPED, previous_status=info.status)
            )

    async def stop_app(self, app_key: str) -> None:
        """Stop and remove all instances for a given app key.

        Args:
            app_key: The app key to stop
        """
        async with self._get_app_key_lock(app_key):
            await self._stop_app_unlocked(app_key)

    async def _stop_app_unlocked(self, app_key: str) -> None:
        """Unregister and shut down all instances for a given app key.

        Caller must hold ``self._get_app_key_lock(app_key)``. Extracted from ``stop_app`` so
        ``reload_app`` can acquire the app-key lock once and call both the stop and start bodies
        without deadlocking on the non-reentrant ``asyncio.Lock``.

        ``registry.unregister_app`` distinguishes "no entries existed at all" (``None``) from
        "entries existed but none were running" (``{}`` — e.g. an app with only failed
        instances). Only the former is actually "not found"; the latter is a normal cleanup of
        failed-only entries and doesn't warrant a misleading "not found" warning.

        ``unregister_app`` discards failed entries silently (it only returns the running ones),
        so without emitting something for them here, the WS status cache for those indices never
        learns the app stopped — it just keeps whatever FAILED status it last cached, indefinitely.
        Snapshotting them before the discard and emitting STOPPED closes that gap the same way
        ``_start_app_unlocked`` closes the equivalent gap for newly-recorded failures.
        """
        try:
            failed_infos = self.registry.get_failed_instance_infos(app_key)
            instances = self.registry.unregister_app(app_key)
            if instances is None:
                self.logger.warning("Cannot stop app %s, not found", app_key)
                return

            await self._emit_stopped_events(failed_infos)

            if not instances:
                self.logger.debug("Cleared failed entries for app %s; no running instances to shut down", app_key)
                return

            await self.shutdown_instances(instances)
        except Exception:
            self.logger.error("Failed to stop app %s:\n%s", app_key, get_short_traceback())

    async def reload_app(
        self,
        app_key: str,
        force_reload: bool = False,
        *,
        admission_mode: AppAdmissionMode = AppAdmissionMode.REJECT_IF_UNRELEASED,
    ) -> None:
        """Stop and reinitialize a single app by key (based on current config).

        Args:
            app_key: The app key to reload
            force_reload: Whether to force-reload the app class from disk
        """
        self.logger.debug("Reloading app %s", app_key)
        await self._admit_start(app_key=app_key, admission_mode=admission_mode)
        try:
            # Acquire the app-key lock once and call the unlocked stop/start bodies directly —
            # calling the public stop_app()/start_app() here (each of which also acquires this
            # lock) would deadlock on the non-reentrant asyncio.Lock.
            async with self._get_app_key_lock(app_key):
                await self._stop_app_unlocked(app_key)

                app_manifest = self._resolve_manifest(app_key)
                if not app_manifest:
                    return

                await self._start_app_unlocked(app_key, app_manifest, force_reload)
        except AppBlockedError:
            # The stop above already ran — a blocked-but-running instance (e.g. left over
            # from before this guard existed, or from an --app filter change that never
            # auto-stops already-running apps) is still cleaned up. Only the restart is
            # refused, and the caller must see that refusal rather than a lying "reloaded".
            raise
        except Exception:
            self.logger.error("Failed to reload app %s:\n%s", app_key, get_short_traceback())

    def _instance_index_in_range(self, app_key: str, index: int, app_manifest: "AppManifest") -> bool:
        """Check ``index`` against the current manifest's instance count.

        Shared by ``reload_instance``, ``stop_instance``, and ``start_instance`` — all three
        must re-validate the index after acquiring the per-app-key lock, mirroring
        ``start_app()``'s post-lock re-fetch pattern, since the manifest (and therefore the
        valid index range) can change while a caller was parked in ``_admit_start()``.
        ``stop_instance`` consults this only for an index the registry no longer tracks: a
        tracked out-of-range instance is an orphan that must stay stoppable.
        """
        valid_index_count = len(self.factory.normalize_configs(app_manifest.app_config))
        if index < 0 or index >= valid_index_count:
            self.logger.debug(
                "Instance %d of app %s is out of range (%d configured) — skipping",
                index,
                app_key,
                valid_index_count,
            )
            return False
        return True

    async def _emit_failure_event_if_present(self, app_key: str, index: int) -> bool:
        """Emit a FAILED ``HassetteAppStateEvent`` for ``index`` if it currently has a failed entry.

        Scoped to the single target index (not the app-key-wide ``get_failed_instance_infos``
        resync that ``_start_app_unlocked`` performs) — a per-instance operation must not
        re-broadcast an unrelated sibling instance's failure. Returns True if an event was
        emitted (i.e. the create attempt at ``index`` failed), so callers can short-circuit.
        """
        failed_infos = self.registry.get_failed_instance_infos(app_key)
        info = failed_infos.get(index)
        if info is None:
            return False
        await self.hassette.send_event(HassetteAppStateEvent.from_instance_info(info))
        return True

    async def _create_instance_unlocked(
        self, app_key: str, index: int, app_manifest: "AppManifest", force_reload: bool = False
    ) -> None:
        """Load the class, create, and initialize a single instance at ``index``.

        Caller must hold ``self._get_app_key_lock(app_key)`` and have already validated that
        ``index`` is within the current manifest's instance count. Shared by
        ``_reload_instance_unlocked`` (after stopping the old instance) and ``start_instance``
        (nothing to stop first).

        Also the authoritative guard against starting an instance of a blocked app: a blocked
        app's manifest still exists and still reports a configured instance count, so a
        not-yet-tracked index still gets a synthetic ``STOPPED`` placeholder in
        ``build_manifest_info()`` and stays addressable by index-range and already-running
        checks alone. Without this check, the web UI's per-instance Start button (and the CLI's
        ``app start --instance``) could start an instance the exclusive-app filter excluded.

        Raises (rather than a silent no-op) so the web route and CLI surface an actionable
        rejection instead of reporting success for a request nothing acted on — see
        ``_start_app_unlocked``'s matching guard for the same reasoning. ``start_instance()``
        and ``_reload_instance_unlocked()``'s caller (``reload_instance()``) both special-case
        this exception to re-raise past their otherwise-swallowing try/except.
        """
        if self.registry.is_blocked(app_key):
            raise AppBlockedError(f"App {app_key!r} is blocked by the --app filter")

        app_class = self.factory.load_class(app_key, app_manifest, force_reload)
        if app_class is None:
            load_error = self.factory.get_load_error(app_manifest)
            self.registry.record_failure(app_key, index, load_error)
            await self._emit_failure_event_if_present(app_key, index)
            return

        app_configs = self.factory.normalize_configs(app_manifest.app_config)
        config_dict = app_configs[index]
        self.factory.create_single_instance(app_key, app_manifest, index, config_dict, app_class)

        try:
            if await self._emit_failure_event_if_present(app_key, index):
                return

            inst = self.registry.get(app_key, index)
            if inst is None:
                return

            await self.hassette.send_event(HassetteAppStateEvent.from_app(app=inst, status=NOT_STARTED))
            await self.initialize_instances(app_key, {index: inst}, app_manifest, instance_index=index)
        except Exception:
            phantom = self.registry.get(app_key, index)
            if phantom is not None:
                await self.cleanup_failed_instance(phantom)
            self.registry.unregister_app(app_key, index)
            self.registry.record_failure(app_key, index, Exception(f"Post-registration failure for {app_key}[{index}]"))
            await self._emit_failure_event_if_present(app_key, index)
            raise

    async def _stop_instance_unlocked(self, app_key: str, index: int) -> None:
        """Unregister and shut down a single instance at ``index``, if one exists.

        Caller must hold ``self._get_app_key_lock(app_key)``. Scopes failed-entry capture to
        the target index only (not the app-key-wide ``get_failed_instance_infos``), mirroring
        ``_stop_app_unlocked``'s discarded-failed-entry handling but for one instance instead
        of the whole app key — so restarting one instance never emits a STOPPED event for an
        unrelated sibling's failed entry.

        Wraps its body in try/except, mirroring ``_stop_app_unlocked`` — this keeps the
        unguarded public ``stop_instance()`` (and ``_reload_instance_unlocked``, which calls
        this before creating the replacement) from letting a shutdown failure escape uncaught.
        """
        try:
            failed_infos = self.registry.get_failed_instance_infos(app_key)
            target_failed_info = failed_infos.get(index)
            instances = self.registry.unregister_app(app_key, index)

            if target_failed_info is not None:
                await self._emit_stopped_events({index: target_failed_info})

            if instances:
                await self.shutdown_instances(instances)
        except Exception:
            self.logger.error("Failed to stop instance %d of app %s:\n%s", index, app_key, get_short_traceback())

    async def reload_instance(
        self,
        app_key: str,
        index: int,
        force_reload: bool = False,
        *,
        admission_mode: AppAdmissionMode = AppAdmissionMode.REJECT_IF_UNRELEASED,
    ) -> None:
        """Stop and reinitialize a single instance of an app by key and index (current config).

        Args:
            app_key: The app key
            index: The instance index to reload
            force_reload: Whether to force-reload the app class from disk
        """
        self.logger.debug("Reloading instance %d of app %s", index, app_key)
        await self._admit_start(app_key=app_key, admission_mode=admission_mode)
        try:
            async with self._get_app_key_lock(app_key):
                await self._reload_instance_unlocked(app_key, index, force_reload)
        except AppBlockedError:
            # The stop half of the reload already ran (see _reload_instance_unlocked) — only
            # the restart is refused, and the caller must see that refusal rather than a
            # lying "reloaded". Mirrors reload_app()'s identical special-casing.
            raise
        except Exception:
            self.logger.error("Failed to reload instance %d of app %s:\n%s", index, app_key, get_short_traceback())

    async def _reload_instance_unlocked(self, app_key: str, index: int, force_reload: bool = False) -> None:
        """Stop and reinitialize a single instance.

        Caller must hold ``self._get_app_key_lock(app_key)``. Extracted so ``apply_changes()``
        can acquire the lock once and reload several changed indices for the same app_key as a
        single atomic batch (see design doc "Data flow for selective restart").
        """
        app_manifest = self._resolve_manifest(app_key)
        if not app_manifest:
            return

        if not self._instance_index_in_range(app_key, index, app_manifest):
            return

        await self._stop_instance_unlocked(app_key, index)
        await self._create_instance_unlocked(app_key, index, app_manifest, force_reload)

    async def stop_instance(self, app_key: str, index: int) -> None:
        """Stop and remove a single instance for a given app key and index.

        No admission check — matches the existing ``stop_app`` convention, which works before
        bootstrap release too.

        Args:
            app_key: The app key
            index: The instance index to stop
        """
        async with self._get_app_key_lock(app_key):
            app_manifest = self.registry.get_manifest(app_key)
            if app_manifest is not None and not self._instance_index_in_range(app_key, index, app_manifest):
                # A still-tracked instance whose index fell outside the configured range (the
                # config shrank while it was still running) stays stoppable.
                # `prune_stale_failed_indices` only prunes stale *failed* entries, so a running
                # orphan would otherwise have no way to be shut down.
                if index not in self.registry.get_instances(app_key):
                    return
            await self._stop_instance_unlocked(app_key, index)

    async def start_instance(
        self,
        app_key: str,
        index: int,
        *,
        admission_mode: AppAdmissionMode = AppAdmissionMode.REJECT_IF_UNRELEASED,
    ) -> None:
        """Create and initialize a single instance for a given app key and index.

        No-ops if the target index is already running — unlike ``reload_instance``, this does
        not stop-then-recreate. Starting over a live instance without stopping it first would
        overwrite the registry entry (``register_app()`` replaces any prior entry at that index)
        while leaving the original instance's listeners, scheduler jobs, and tasks running but
        unreachable by later stop/shutdown calls. Callers that want a fresh instance should use
        ``reload_instance`` instead.

        Args:
            app_key: The app key
            index: The instance index to start
        """
        app_manifest = self._resolve_manifest(app_key)
        if not app_manifest:
            return

        await self._admit_start(app_key=app_key, admission_mode=admission_mode)

        try:
            async with self._get_app_key_lock(app_key):
                # Re-fetch under the lock — mirrors start_app()'s stale-manifest race guard.
                app_manifest = self._resolve_manifest(app_key)
                if not app_manifest:
                    return

                if not self._instance_index_in_range(app_key, index, app_manifest):
                    return

                if self.registry.get(app_key, index) is not None:
                    self.logger.debug("Instance %d of app %s is already running — skipping start", index, app_key)
                    return

                await self._create_instance_unlocked(app_key, index, app_manifest)
        except AppBlockedError:
            raise
        except Exception:
            self.logger.error("Failed to start instance %d of app %s:\n%s", index, app_key, get_short_traceback())
