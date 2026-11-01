"""AppStartStopMixin — app-level and instance-level start/stop/reload."""

import typing
from collections.abc import Awaitable, Callable
from logging import Logger

from hassette.core.app_lifecycle_common import (
    ALREADY_RUNNING_REASON,
    ALREADY_STOPPED_REASON,
    BAD_CONFIGURATION_PREFIX,
    CLASS_LOAD_FAILED_PREFIX,
    CLEARED_FAILURE_REASON,
    FAILED,
    NOT_IN_CONFIG_REASON,
    NOT_STARTED,
    STOPPED,
    ActionOutcomes,
    AppAdmissionMode,
    failure_reason,
)
from hassette.events.hassette import HassetteAppStateEvent
from hassette.exceptions import (
    AppBlockedError,
    AppRemovedError,
    InvalidInheritanceError,
    UndefinedUserConfigError,
)
from hassette.resources.lifecycle import skip_own_shutdown_hooks
from hassette.utils.exception_utils import get_short_traceback

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.config.classes import AppManifest
    from hassette.core.app_factory import AppFactory
    from hassette.core.app_key_lock import AppKeyLock
    from hassette.core.app_registry import AppRegistry
    from hassette.resources.shutdown_outcome import ShutdownOutcome
    from hassette.schemas.app_outcomes import InstanceOutcome
    from hassette.schemas.app_snapshots import AppInstanceInfo

"""Failure ``reason`` for an instance action whose index a config change removed while the action waited."""


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
    shutdown_instance: "Callable[..., Awaitable[ShutdownOutcome | None]]"
    shutdown_instances: "Callable[..., Awaitable[ShutdownOutcome]]"

    async def start_app(
        self,
        app_key: str,
        force_reload: bool = False,
        *,
        admission_mode: AppAdmissionMode = AppAdmissionMode.REJECT_IF_UNRELEASED,
    ) -> "tuple[InstanceOutcome, ...]":
        """Create instances for an app and await their initialization.

        No-ops for any index that already has a live registry entry (``succeeded``, "already running") —
        calling start on an already-running app does not recreate its instances. ``force_reload`` is likewise
        ignored whenever any instance of this app_key is already running, since reloading the
        shared class out from under a live instance would leave it and any newly-created
        sibling on two different class versions. Use ``reload_app()`` to stop-then-recreate
        with a fresh class.

        Args:
            app_key: The app key to start
            force_reload: Whether to force-reload the app class from disk
            admission_mode: What to do if bootstrap has not released yet: wait for release, or raise
                ``AppBootstrapNotReleasedError``.

        Returns:
            One outcome per configured instance, in index order.

        Raises:
            AppRemovedError: The app has no manifest (disabled, or removed from config).
            AppBlockedError: The app is blocked by the ``--app`` filter.
        """
        self._require_manifest(app_key)

        await self._admit_start(app_key=app_key, admission_mode=admission_mode)

        async with self._get_app_key_lock(app_key):
            # Re-fetch under the lock: _admit_start() can block indefinitely (WAIT_FOR_RELEASE
            # awaits AppBootstrapCoordinator's release latch), and a concurrent file-watcher
            # reconciliation can remove or replace this app's manifest while that wait is
            # parked. Acting on the pre-wait manifest would create instances for an app that
            # no longer exists (or no longer matches current config).
            app_manifest = self._require_manifest(app_key)
            outcomes = self._outcomes_for(app_key, self._configured_indices(app_manifest))
            try:
                await self._start_app_unlocked(app_key, app_manifest, force_reload, outcomes=outcomes)
            except AppBlockedError:
                raise
            except Exception as exc:
                self.logger.error("Failed to start app %s:\n%s", app_key, get_short_traceback())
                return outcomes.finish(failure_reason(exc))
            return outcomes.finish()

    def _require_manifest(self, app_key: str, outcomes: "tuple[InstanceOutcome, ...]" = ()) -> "AppManifest":
        """Return ``app_key``'s manifest, or raise ``AppRemovedError`` carrying ``outcomes`` when it is gone."""
        app_manifest = self._resolve_manifest(app_key)
        if app_manifest is None:
            raise AppRemovedError(f"App {app_key!r} is not configured", outcomes=outcomes)
        return app_manifest

    def _configured_indices(self, app_manifest: "AppManifest") -> range:
        """The indices ``app_manifest`` configures."""
        return range(len(self.factory.normalize_configs(app_manifest.app_config)))

    def _outcomes_for(self, app_key: str, indices: "typing.Iterable[int]") -> ActionOutcomes:
        """A new request's outcomes, targeting ``indices`` of ``app_key``."""
        return ActionOutcomes(self._target_names(app_key, indices))

    def _target_names(self, app_key: str, indices: "typing.Iterable[int]") -> dict[int, str]:
        """Each of ``indices`` of ``app_key`` mapped to its instance name, as ``ActionOutcomes`` targets them."""
        return {index: self.registry.instance_name(app_key, index) for index in indices}

    async def _start_app_unlocked(
        self, app_key: str, app_manifest: "AppManifest", force_reload: bool, *, outcomes: ActionOutcomes
    ) -> None:
        """Create instances for an app and await their initialization, recording each configured index's outcome.

        Caller must hold ``self._get_app_key_lock(app_key)``, and ``outcomes`` must target every
        configured index of ``app_manifest``. Extracted from ``start_app`` so
        ``reload_app`` can acquire the app-key lock once and call both the stop and start bodies
        without deadlocking on the non-reentrant ``asyncio.Lock`` (calling the public,
        lock-acquiring `start_app`/`stop_app` from inside an already-held lock would hang).
        """
        if self.registry.is_blocked(app_key):
            # A blocked app's manifest still exists and still reports a configured instance
            # count, so it stays addressable by every check above this one — this is the only
            # thing standing between a manual start/reload and bypassing the exclusive-app
            # filter that blocked it in the first place. Raises so the web route and CLI surface an
            # actionable rejection instead of reporting success for a request nothing acted on;
            # start_app() and reload_app() re-raise it past their catch-all. It carries the outcomes
            # of a reload's stop half, which really ran.
            raise AppBlockedError(f"App {app_key!r} is blocked by the --app filter", outcomes=outcomes.snapshot())

        # The config can change while a reload's stop half runs, so its create half may find more indices.
        outcomes.add_targets(self._target_names(app_key, self._configured_indices(app_manifest)))

        # A prior, larger config can leave failed entries at indices the *current* config no
        # longer has — e.g. an autostart=false app that wasn't auto-reconciled on the config
        # change (see should_auto_reconcile) and is now being started manually. Prune those
        # before create_instances() runs (not inside it), so pruning applies uniformly whether
        # or not class-loading itself fails, and so pruned entries can be reported as STOPPED —
        # unregister_app()-style silent discarding leaves the WS status cache for that index
        # stuck on FAILED forever (see _stop_app_unlocked for the same problem on the stop side).
        # A no-op on the reload_app() path: _stop_app_unlocked() already removed every failed entry
        # for app_key before this runs, so there's nothing left to prune. This only ever does real
        # work for a standalone start_app() call.
        valid_index_count = len(self._configured_indices(app_manifest))
        await self._emit_discarded_entry_events(self.registry.prune_stale_failed_indices(app_key, valid_index_count))

        try:
            self.logger.debug("Creating instances for app %s", app_key)
            created_indices = self.factory.create_instances(
                app_key, app_manifest, force_reload=force_reload, outcomes=outcomes
            )
        except (UndefinedUserConfigError, InvalidInheritanceError) as exc:
            self.logger.error(
                "Failed to load app '%s' due to bad configuration - check previous logs for details", app_key
            )
            outcomes.fail_undecided(f"{BAD_CONFIGURATION_PREFIX}{failure_reason(exc)}")
            return
        except Exception as exc:
            self.logger.error("Failed to load app class for '%s':\n%s", app_key, get_short_traceback())
            outcomes.fail_undecided(f"{CLASS_LOAD_FAILED_PREFIX}{failure_reason(exc)}")
            return

        # create_instances() records failures (config validation, class
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
            await self.initialize_instances(
                app_key, instances, app_manifest, only_indices=created_indices, outcomes=outcomes
            )

    async def _emit_discarded_entry_events(self, infos: "dict[int, AppInstanceInfo]") -> None:
        """Emit an event for each discarded failed-entry snapshot: STOPPED, or FAILED for a flagged one.

        Shared by ``_start_app_unlocked`` (entries pruned for being outside the current config's
        range) and the stop paths (failed entries discarded with no teardown to run) — both
        remove a failed entry from the registry without an App object to build an event from,
        and both need the WS status cache to learn the entry is gone rather than staying stuck on
        FAILED forever. An index flagged needs-restart keeps reporting FAILED until restart, so its
        event says FAILED rather than STOPPED.
        """
        for info in infos.values():
            status = FAILED if info.needs_restart is not None else STOPPED
            await self.hassette.send_event(
                HassetteAppStateEvent.from_instance_info(info, status=status, previous_status=info.status)
            )

    async def stop_app(self, app_key: str) -> "tuple[InstanceOutcome, ...]":
        """Stop and remove all instances for a given app key.

        Args:
            app_key: The app key to stop

        Returns:
            One outcome per targeted instance, in index order: every configured index, plus any tracked
            index outside the config. An index flagged needs-restart is ``refused`` (spec 140 D3); one with
            nothing to stop is ``succeeded``, "already stopped".
        """
        async with self._get_app_key_lock(app_key):
            outcomes = self._outcomes_for(app_key, self._stop_targets(app_key))
            await self._stop_app_unlocked(app_key, outcomes=outcomes)
            return outcomes.finish()

    def _stop_targets(self, app_key: str) -> set[int]:
        """A whole-app stop's targets: every configured index, plus any tracked index outside the config."""
        app_manifest = self.registry.get_manifest(app_key)
        configured = self._configured_indices(app_manifest) if app_manifest is not None else []
        return set(configured) | self.registry.tracked_indices(app_key)

    async def _stop_app_unlocked(self, app_key: str, *, outcomes: ActionOutcomes) -> None:
        """Shut down all instances for a given app key, recording each target's outcome.

        Caller must hold ``self._get_app_key_lock(app_key)``. Extracted from ``stop_app`` so
        ``reload_app`` can acquire the app-key lock once and call both the stop and start bodies
        without deadlocking on the non-reentrant ``asyncio.Lock``.

        Only an app key with no targets is "not found".

        Running instances stay registered through their teardown: ``shutdown_instance`` unregisters
        each one itself, between its teardown and its outcome, so readers never see a STOPPED
        placeholder while ``on_shutdown`` still runs. Indices holding only a failure entry have no
        teardown; they are discarded per index up front with a STOPPED event (FAILED when flagged
        needs-restart), so the WS status cache doesn't keep a stale FAILED for them indefinitely.
        """
        if not outcomes.indices:
            self.logger.warning("Cannot stop app %s, not found", app_key)
            return
        self._record_untracked_stops(app_key, outcomes.indices, outcomes=outcomes)
        try:
            instances = self.registry.get_running_apps(app_key)
            await self._discard_failed_indices(
                app_key, self.registry.tracked_indices(app_key) - set(instances), outcomes=outcomes
            )
            if instances:
                await self.shutdown_instances(instances, outcomes=outcomes)
        except Exception as exc:
            self.logger.error("Failed to stop app %s:\n%s", app_key, get_short_traceback())
            outcomes.fail_undecided(failure_reason(exc))
        self._refuse_flagged_stops(app_key, outcomes.indices, outcomes=outcomes)

    def _record_untracked_stops(
        self, app_key: str, indices: "typing.Iterable[int]", *, outcomes: ActionOutcomes
    ) -> None:
        """Record each of ``indices`` the registry doesn't track as ``succeeded``, "already stopped" (spec 140 D1).

        Decided when the stop picks its targets, so a target its teardown never recorded fails at ``finish``
        instead of passing as stopped.
        """
        tracked = self.registry.tracked_indices(app_key)
        for index in indices:
            if index not in tracked:
                outcomes.succeeded(index, ALREADY_STOPPED_REASON)

    def _refuse_flagged_stops(self, app_key: str, indices: "typing.Iterable[int]", *, outcomes: ActionOutcomes) -> None:
        """Record each of ``indices`` flagged needs-restart as ``refused``, over whatever its teardown recorded.

        A flagged index's work may still be running, so a stop never reports it stopped (spec 140 D3). One this
        stop flagged keeps its failure, since ``ActionOutcomes`` never replaces a newly flagged outcome. Scoped to
        the caller's indices: concurrent per-index stops can share one collector.
        """
        for index in indices:
            if (refusal := self.registry.refusal_reason(app_key, index)) is not None:
                outcomes.refused(index, refusal)

    async def _discard_failed_indices(self, app_key: str, indices: set[int], *, outcomes: ActionOutcomes) -> None:
        """Discard the failure entries at ``indices`` (none of them running), emit their events, and record each.

        ``unregister_app`` removes only the failure entry, never a needs-restart record, so a flagged
        index stays FAILED after this and its event says FAILED (``_emit_discarded_entry_events``).
        """
        failed_infos = self.registry.get_failed_instance_infos(app_key)
        discarded = {index: info for index, info in failed_infos.items() if index in indices}
        for index in discarded:
            self.registry.unregister_app(app_key, index)
            outcomes.succeeded(index, CLEARED_FAILURE_REASON)
        await self._emit_discarded_entry_events(discarded)

    async def reload_app(
        self,
        app_key: str,
        force_reload: bool = False,
        *,
        admission_mode: AppAdmissionMode = AppAdmissionMode.REJECT_IF_UNRELEASED,
    ) -> "tuple[InstanceOutcome, ...]":
        """Stop and reinitialize a single app by key (based on current config).

        Each index's outcome is its create half's, except that a stop half which flagged the index
        needs-restart stands (spec 140 D6).

        Args:
            app_key: The app key to reload
            force_reload: Whether to force-reload the app class from disk
            admission_mode: What to do if bootstrap has not released yet: wait for release, or raise
                ``AppBootstrapNotReleasedError``.

        Returns:
            One outcome per targeted instance, in index order: every configured index, plus any tracked
            index outside the config, which is only stopped.

        Raises:
            AppRemovedError: The app's manifest was gone after the stop half; carries the stop half's outcomes.
            AppBlockedError: The app is blocked by the ``--app`` filter; carries the stop half's outcomes.
        """
        self.logger.debug("Reloading app %s", app_key)
        await self._admit_start(app_key=app_key, admission_mode=admission_mode)
        # Acquire the app-key lock once and call the unlocked stop/start bodies directly —
        # calling the public stop_app()/start_app() here (each of which also acquires this
        # lock) would deadlock on the non-reentrant asyncio.Lock.
        async with self._get_app_key_lock(app_key):
            outcomes = self._outcomes_for(app_key, self._stop_targets(app_key))
            try:
                await self._stop_app_unlocked(app_key, outcomes=outcomes)

                app_manifest = self._require_manifest(app_key, outcomes.snapshot())
                outcomes.begin_create_half(self._configured_indices(app_manifest))
                await self._start_app_unlocked(app_key, app_manifest, force_reload, outcomes=outcomes)
            except (AppBlockedError, AppRemovedError):
                # The stop above already ran — a blocked-but-running instance (e.g. left over
                # from before this guard existed, or from an --app filter change that never
                # auto-stops already-running apps) is still cleaned up. Only the restart is
                # refused, and the caller must see that refusal rather than a lying "reloaded".
                raise
            except Exception as exc:
                self.logger.error("Failed to reload app %s:\n%s", app_key, get_short_traceback())
                return outcomes.finish(failure_reason(exc))
            return outcomes.finish()

    def _instance_index_in_range(self, app_key: str, index: int, app_manifest: "AppManifest") -> bool:
        """Check ``index`` against the current manifest's instance count.

        Shared by ``reload_instance``, ``start_instance`` and a config change's per-index restarts.
        Each re-validates the index after acquiring the per-app-key lock, mirroring
        ``start_app()``'s post-lock re-fetch pattern, since the manifest (and therefore the
        valid index range) can change while a caller was parked in ``_admit_start()``.
        ``stop_instance`` doesn't use it: an out-of-range index it doesn't track has nothing to
        stop, and one it tracks is an orphan that must stay stoppable.
        """
        valid_index_count = len(self._configured_indices(app_manifest))
        if index < 0 or index >= valid_index_count:
            self.logger.debug(
                "Instance %d of app %s is out of range (%d configured) — skipping",
                index,
                app_key,
                valid_index_count,
            )
            return False
        return True

    async def _emit_failure_event_if_present(self, app_key: str, index: int) -> None:
        """Emit a FAILED ``HassetteAppStateEvent`` for ``index`` if it currently has a failed entry.

        Scoped to the single target index (not the app-key-wide ``get_failed_instance_infos``
        resync that ``_start_app_unlocked`` performs) — a per-instance operation must not
        re-broadcast an unrelated sibling instance's failure.
        """
        info = self.registry.get_failed_instance_infos(app_key).get(index)
        if info is not None:
            await self.hassette.send_event(HassetteAppStateEvent.from_instance_info(info))

    async def _create_instance_unlocked(
        self,
        app_key: str,
        index: int,
        app_manifest: "AppManifest",
        force_reload: bool = False,
        *,
        outcomes: ActionOutcomes,
    ) -> None:
        """Load the class, create, and initialize a single instance at ``index``, recording its outcome.

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

        The blocked check raises (rather than a silent no-op) so the web route and CLI surface an
        actionable rejection instead of reporting success for a request nothing acted on — see
        ``_start_app_unlocked``'s matching guard for the same reasoning. ``start_instance()``
        and ``_reload_instance_unlocked()``'s caller (``reload_instance()``) both special-case
        this exception to re-raise past their otherwise-swallowing try/except.

        An index flagged as needing a hassette restart is the exception: it is recorded as refused and
        returns without raising or logging (see the check below for why).
        """
        if self.registry.is_blocked(app_key):
            raise AppBlockedError(f"App {app_key!r} is blocked by the --app filter", outcomes=outcomes.snapshot())

        # The old instance at a flagged index may still be running work, so no replacement is created over
        # it. Checked before load_class(), so a refused index never re-imports the module or records a
        # class-load failure over its flag. Recorded rather than raised or logged: an HTTP request reports it
        # in its response, and a caller with no response logs it once (log_refusals).
        if (refusal := self.registry.refusal_reason(app_key, index)) is not None:
            outcomes.refused(index, refusal)
            return

        app_class = self.factory.load_class(app_key, app_manifest, force_reload)
        if app_class is None:
            load_error = self.factory.get_load_error(app_manifest)
            self.registry.record_failure(app_key, index, load_error)
            outcomes.failed(index, f"{CLASS_LOAD_FAILED_PREFIX}{failure_reason(load_error)}")
            await self._emit_failure_event_if_present(app_key, index)
            return

        app_configs = self.factory.normalize_configs(app_manifest.app_config)
        config_dict = app_configs[index]
        self.factory.create_single_instance(app_key, app_manifest, index, config_dict, app_class, outcomes=outcomes)

        # Set just before initialize_instances() is called. initialize_instances() settles its own
        # init failures (shutdown_instance with a cause) and doesn't raise them, so an exception after
        # this point comes from post-ready reconciliation: the app initialized, and its shutdown hooks
        # may run. An exception before it means the instance never started, so its hooks must not run.
        init_started = False
        try:
            inst = self.registry.get(app_key, index)
            if inst is None:
                # create_single_instance() recorded a failure instead of registering an instance.
                await self._emit_failure_event_if_present(app_key, index)
                return

            await self.hassette.send_event(HassetteAppStateEvent.from_app(app=inst, status=NOT_STARTED))
            init_started = True
            await self.initialize_instances(
                app_key, {index: inst}, app_manifest, instance_name=inst.app_config.instance_name, outcomes=outcomes
            )
        except Exception as exc:
            phantom = self.registry.get(app_key, index)
            if phantom is not None:
                # Still registered: the instance either initialized and then something after it
                # raised (reconciliation), or never started. Either way it goes through shutdown,
                # under the entry deadline, and is flagged if its work may still be running.
                if not init_started:
                    skip_own_shutdown_hooks(phantom)
                await self.shutdown_instance(phantom, index, cause=exc, outcomes=outcomes)
            else:
                failure = Exception(f"Post-registration failure for {app_key}[{index}]")
                self.registry.record_failure(app_key, index, failure)
                outcomes.failed(index, str(failure))
                await self._emit_failure_event_if_present(app_key, index)
            raise

    async def _stop_instance_unlocked(self, app_key: str, index: int, *, outcomes: ActionOutcomes) -> None:
        """Shut down a single instance at ``index``, if one exists, and record its outcome.

        Caller must hold ``self._get_app_key_lock(app_key)``. Scoped to the target index only,
        mirroring ``_stop_app_unlocked`` but for one instance instead of the whole app key — so
        restarting one instance never emits a STOPPED event for an unrelated sibling's failed
        entry. A running instance stays registered until ``shutdown_instance`` unregisters it
        after its teardown; an index holding only a failure entry is discarded up front.

        Wraps its body in try/except, mirroring ``_stop_app_unlocked`` — this keeps the
        unguarded public ``stop_instance()`` (and ``_reload_instance_unlocked``, which calls
        this before creating the replacement) from letting a shutdown failure escape uncaught.
        """
        self._record_untracked_stops(app_key, [index], outcomes=outcomes)
        try:
            inst = self.registry.get(app_key, index)
            if inst is None:
                await self._discard_failed_indices(app_key, {index}, outcomes=outcomes)
            else:
                await self.shutdown_instances({index: inst}, outcomes=outcomes)
        except Exception as exc:
            self.logger.error("Failed to stop instance %d of app %s:\n%s", index, app_key, get_short_traceback())
            outcomes.fail_undecided(failure_reason(exc), [index])
        self._refuse_flagged_stops(app_key, [index], outcomes=outcomes)

    async def reload_instance(
        self,
        app_key: str,
        index: int,
        force_reload: bool = False,
        *,
        admission_mode: AppAdmissionMode = AppAdmissionMode.REJECT_IF_UNRELEASED,
    ) -> "tuple[InstanceOutcome, ...]":
        """Stop and reinitialize a single instance of an app by key and index (current config).

        Its outcome is the create half's, except that a stop half which flagged the index needs-restart
        stands (spec 140 D6).

        Args:
            app_key: The app key
            index: The instance index to reload
            force_reload: Whether to force-reload the app class from disk
            admission_mode: What to do if bootstrap has not released yet: wait for release, or raise
                ``AppBootstrapNotReleasedError``.

        Returns:
            The instance's outcome, as a one-item tuple.

        Raises:
            AppRemovedError: The app has no manifest once the lock is held.
            AppBlockedError: The app is blocked by the ``--app`` filter; carries the stop half's outcome.
        """
        self.logger.debug("Reloading instance %d of app %s", index, app_key)
        await self._admit_start(app_key=app_key, admission_mode=admission_mode)
        async with self._get_app_key_lock(app_key):
            outcomes = self._outcomes_for(app_key, [index])
            try:
                await self._reload_instance_unlocked(app_key, index, force_reload, outcomes=outcomes)
            except (AppBlockedError, AppRemovedError):
                # The stop half of the reload may already have run (see _reload_instance_unlocked) — only
                # the restart is refused, and the caller must see that refusal rather than a
                # lying "reloaded". Mirrors reload_app()'s identical special-casing.
                raise
            except Exception as exc:
                self.logger.error("Failed to reload instance %d of app %s:\n%s", index, app_key, get_short_traceback())
                return outcomes.finish(failure_reason(exc))
            return outcomes.finish()

    async def _reload_instance_unlocked(
        self, app_key: str, index: int, force_reload: bool = False, *, outcomes: ActionOutcomes
    ) -> None:
        """Stop and reinitialize a single instance, recording its outcome.

        Caller must hold ``self._get_app_key_lock(app_key)``; ``reload_instance`` takes it.
        """
        app_manifest = self._require_manifest(app_key)

        if not self._instance_index_in_range(app_key, index, app_manifest):
            outcomes.failed(index, NOT_IN_CONFIG_REASON)
            return

        await self._stop_instance_unlocked(app_key, index, outcomes=outcomes)
        outcomes.begin_create_half([index])
        await self._create_instance_unlocked(app_key, index, app_manifest, force_reload, outcomes=outcomes)

    async def stop_instance(self, app_key: str, index: int) -> "tuple[InstanceOutcome, ...]":
        """Stop and remove a single instance for a given app key and index.

        No admission check — matches the existing ``stop_app`` convention, which works before
        bootstrap release too. No range check either: a still-tracked instance whose index fell outside
        the configured range (the config shrank while it was still running) stays stoppable, and an
        untracked index has nothing to stop.

        Args:
            app_key: The app key
            index: The instance index to stop

        Returns:
            The instance's outcome, as a one-item tuple: ``refused`` when it is flagged needs-restart
            (spec 140 D3), ``succeeded`` "already stopped" when nothing was there to stop.
        """
        async with self._get_app_key_lock(app_key):
            outcomes = self._outcomes_for(app_key, [index])
            await self._stop_instance_unlocked(app_key, index, outcomes=outcomes)
            return outcomes.finish()

    async def start_instance(
        self,
        app_key: str,
        index: int,
        *,
        admission_mode: AppAdmissionMode = AppAdmissionMode.REJECT_IF_UNRELEASED,
    ) -> "tuple[InstanceOutcome, ...]":
        """Create and initialize a single instance for a given app key and index.

        No-ops (``succeeded``, "already running") if the target index is already running — unlike
        ``reload_instance``, this does not stop-then-recreate. Starting over a live instance without
        stopping it first would overwrite the registry entry (``register_app()`` replaces any prior entry at that index)
        while leaving the original instance's listeners, scheduler jobs, and tasks running but
        unreachable by later stop/shutdown calls. Callers that want a fresh instance should use
        ``reload_instance`` instead.

        Args:
            app_key: The app key
            index: The instance index to start
            admission_mode: What to do if bootstrap has not released yet: wait for release, or raise
                ``AppBootstrapNotReleasedError``.

        Returns:
            The instance's outcome, as a one-item tuple.

        Raises:
            AppRemovedError: The app has no manifest (disabled, or removed from config).
            AppBlockedError: The app is blocked by the ``--app`` filter.
        """
        self._require_manifest(app_key)

        await self._admit_start(app_key=app_key, admission_mode=admission_mode)

        async with self._get_app_key_lock(app_key):
            # Re-fetch under the lock — mirrors start_app()'s stale-manifest race guard.
            app_manifest = self._require_manifest(app_key)
            outcomes = self._outcomes_for(app_key, [index])
            try:
                if not self._instance_index_in_range(app_key, index, app_manifest):
                    outcomes.failed(index, NOT_IN_CONFIG_REASON)
                elif self.registry.get(app_key, index) is not None:
                    self.logger.debug("Instance %d of app %s is already running — skipping start", index, app_key)
                    outcomes.succeeded(index, ALREADY_RUNNING_REASON)
                else:
                    await self._create_instance_unlocked(app_key, index, app_manifest, outcomes=outcomes)
            except AppBlockedError:
                raise
            except Exception as exc:
                self.logger.error("Failed to start instance %d of app %s:\n%s", index, app_key, get_short_traceback())
                return outcomes.finish(failure_reason(exc))
            return outcomes.finish()
