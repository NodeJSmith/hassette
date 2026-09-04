"""AppLifecycleService — owns app lifecycle orchestration and change handling."""

import asyncio
import typing
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from timeit import default_timer as timer

import anyio
import structlog.contextvars

import hassette.event_handling.accessors as A
from hassette.core.app_change_detector import AppChangeDetector, ChangeSet
from hassette.core.app_factory import AppFactory
from hassette.events.hassette import HassetteAppStateEvent, HassetteSimpleEvent
from hassette.exceptions import (
    AppBlockedError,
    AppBootstrapNotReleasedError,
    InvalidInheritanceError,
    UndefinedUserConfigError,
)
from hassette.resources.base import Resource
from hassette.resources.lifecycle import handle_crash, mark_ready
from hassette.types import ResourceStatus, Topic
from hassette.types.enums import BlockReason
from hassette.types.types import LOG_LEVEL_TYPE
from hassette.utils.exception_utils import get_short_traceback

if typing.TYPE_CHECKING:
    from hassette import AppConfig, Hassette
    from hassette.app.app import App
    from hassette.config.classes import AppManifest
    from hassette.core.app_bootstrap_coordinator import AppBootstrapCoordinator
    from hassette.core.app_registry import AppRegistry
    from hassette.core.bus_service import BusService
    from hassette.schemas.app_snapshots import AppInstanceInfo

try:
    from humanize import precisedelta
except ImportError:  # pragma: no cover
    precisedelta = None  # pyright: ignore[reportAssignmentType]


# Shorten enum references (from AppLifecycleManager)
FAILED = ResourceStatus.FAILED
STARTING = ResourceStatus.STARTING
RUNNING = ResourceStatus.RUNNING
STOPPING = ResourceStatus.STOPPING
STOPPED = ResourceStatus.STOPPED
NOT_STARTED = ResourceStatus.NOT_STARTED

# Deeper than the exception_utils.get_short_traceback default (1): init failures often
# surface several frames deep (anyio.fail_after -> on_initialize -> nested awaits), and a
# single frame is rarely enough to show the app's own code rather than just anyio internals.
# Passed as a negative limit (see call sites below) so traceback.format_exc keeps the frames
# closest to the raise — the app author's own code — instead of the frames closest to this
# module's try block.
INIT_FAILURE_TRACEBACK_LIMIT = 5

# Per-manifest upsert timeout. A failed write degrades one app's dashboard row — it must
# never block app startup or a hot-reload. See design doc "Persist trigger".
MANIFEST_UPSERT_TIMEOUT_SECONDS = 5.0


class AppAdmissionMode(StrEnum):
    WAIT_FOR_RELEASE = "wait_for_release"
    REJECT_IF_UNRELEASED = "reject_if_unreleased"


@dataclass
class PendingReconciliation:
    """A deferred app-config reconciliation, queued while bootstrap release hasn't opened yet.

    Presence of an instance (vs. ``None``) on ``AppLifecycleService._pending_reconciliation``
    is the "is one queued?" signal — see ``_record_pre_release_reconciliation`` and
    ``_take_pre_release_reconciliation``, which are the only code that constructs, merges, or
    clears this record.
    """

    original_apps_config: dict[str, "AppManifest"]
    current_apps_config: dict[str, "AppManifest"]
    changed_paths: frozenset[Path] | None


class AppLifecycleService(Resource):
    """Manages app lifecycle orchestration, change detection, and event emission.

    Folds in all functionality from ``AppLifecycleManager`` and absorbs the
    implementation methods from ``AppHandler`` that deal with starting, stopping,
    reloading, and change-handling of apps.

    Owns:
        - ``AppFactory`` (plain utility, created internally)
        - ``AppChangeDetector`` (plain utility, created internally)

    Receives:
        - ``AppRegistry`` (shared reference from AppHandler)
    """

    registry: "AppRegistry"
    """Shared registry for tracking app state (owned by AppHandler)."""

    factory: AppFactory
    """Factory for creating app instances."""

    change_detector: AppChangeDetector
    """Detector for configuration changes."""

    def __init__(
        self,
        hassette: "Hassette",
        *,
        parent: Resource | None = None,
        registry: "AppRegistry",
    ) -> None:
        super().__init__(hassette, parent=parent)

        self.registry = registry
        self.factory = AppFactory(hassette, self.registry)
        self.change_detector = AppChangeDetector()
        self._pending_reconciliation: PendingReconciliation | None = None
        # Bus dispatch spawns a fresh task per handler invocation rather than awaiting handlers
        # sequentially (see BusService._dispatch), so two file-watcher events arriving close
        # together can produce two concurrently-running handle_change_event() coroutines. Each
        # does real awaited I/O (refresh_config(), resolve_only_apps()) before touching
        # ``_pending_reconciliation``, and refresh_config() mutates self.registry.manifests
        # in place — so overlapping calls can race on the "what was the world like before this
        # change" snapshot. This lock serializes handle_change_event so only one reconciliation
        # pass runs at a time, matching the "single reconciliation in flight" model the rest of
        # this class already assumes.
        self._change_event_lock = asyncio.Lock()
        # Serializes the create->initialize->reconcile pipeline per app_key. Without this, initial
        # bootstrap's parked start_app() call (blocked in _admit_start() on WAIT_FOR_RELEASE) and an
        # independent post-release start_app()/reload_app() call for the same app_key (e.g. a
        # file-watcher reload landing right as release fires) can both reach factory.create_instances()
        # concurrently. AppRegistry.register_app() then overwrites without tearing down the loser's
        # instance, and reconcile_app_registrations() computes live_listener_ids from its own call-local
        # instances snapshot, so the second caller can delete/retire the first caller's still-running
        # listener/job DB rows. Held only around create->initialize->reconcile, never around the
        # (possibly indefinite) admission wait in _admit_start(), so REJECT_IF_UNRELEASED callers keep
        # failing fast instead of retaining a waiting task. Entries accumulate for the life of the
        # process (never pruned on stop_app) — accepted, since growth is bounded by distinct app_keys
        # ever seen, not by request volume.
        self._app_key_locks: dict[str, asyncio.Lock] = {}

    async def on_initialize(self) -> None:
        """Signal readiness immediately — no dependencies to wait for."""
        mark_ready(self, reason="AppLifecycleService initialized")

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        return self.hassette.config.logging.app_handler

    @property
    def startup_timeout(self) -> int:
        """Timeout in seconds for app instance initialization."""
        return self.hassette.config.lifecycle.app_startup_timeout_seconds

    @property
    def shutdown_timeout(self) -> int:
        """Timeout in seconds for app instance shutdown."""
        return self.hassette.config.lifecycle.app_shutdown_timeout_seconds

    @property
    def cleanup_timeout(self) -> int:
        """Timeout in seconds for cleaning up a failed app instance's listeners and jobs."""
        return self.hassette.config.lifecycle.failed_instance_cleanup_timeout_seconds

    async def initialize_instances(
        self,
        app_key: str,
        instances: dict[int, "App[AppConfig]"],
        manifest: "AppManifest",
        instance_index: int | None = None,
    ) -> None:
        """Initialize all instances for an app key.

        Records failures directly to the registry. After all instances are
        initialized, awaits pending DB registrations and runs post-ready
        reconciliation to retire stale rows from previous sessions.

        Args:
            app_key: The app key
            instances: Dict of index -> App to initialize
            manifest: The app manifest
            instance_index: When provided, scopes post-ready reconciliation to this instance
                only, so restarting one instance does not retire sibling instances' rows.
                When None (default), reconciliation is app_key-scoped only — unchanged behavior.
        """
        class_name = manifest.class_name

        for idx, inst in instances.items():
            structlog.contextvars.bind_contextvars(
                app_key=app_key,
                instance_name=inst.app_config.instance_name,
                instance_index=idx,
            )
            try:
                with anyio.fail_after(self.startup_timeout):
                    await inst.initialize()
                    mark_ready(inst, reason="initialized")
                self.logger.debug(
                    "App '%s' (%s) initialized successfully",
                    inst.app_config.instance_name,
                    class_name,
                )
                await self.emit_app_state_change(inst, status=RUNNING, previous_status=STARTING)
            except TimeoutError as exc:
                self.logger.error(
                    "Timed out while starting app '%s' (%s):\n%s",
                    inst.app_config.instance_name,
                    class_name,
                    get_short_traceback(-INIT_FAILURE_TRACEBACK_LIMIT),
                )
                inst.status = STOPPED
                await self.cleanup_failed_instance(inst)
                self.registry.record_failure(app_key, idx, exc)
                await self.emit_app_state_change(inst, status=FAILED, previous_status=STARTING, exception=exc)
            except Exception as exc:
                self.logger.error(
                    "Failed to start app '%s' (%s):\n%s",
                    inst.app_config.instance_name,
                    class_name,
                    get_short_traceback(-INIT_FAILURE_TRACEBACK_LIMIT),
                )
                inst.status = STOPPED
                await self.cleanup_failed_instance(inst)
                self.registry.record_failure(app_key, idx, exc)
                await self.emit_app_state_change(inst, status=FAILED, previous_status=STARTING, exception=exc)
            finally:
                structlog.contextvars.unbind_contextvars("app_key", "instance_name", "instance_index")

        # Post-ready reconciliation: retire stale rows from previous sessions.
        # Runs after the instance loop to ensure all registrations are complete.
        await self.reconcile_app_registrations(app_key, instances, instance_index=instance_index)

    async def cleanup_failed_instance(self, inst: "App[AppConfig]") -> None:
        """Remove bus listeners and scheduler jobs registered by an instance that failed to initialize.

        Bounded by a short timeout so a broken cleanup path cannot turn an init failure into a hang.
        Must run before record_failure, which pops the instance from the registry — after that point,
        the normal shutdown path can never reach these registrations.
        """
        try:
            with anyio.fail_after(self.cleanup_timeout):
                try:
                    inst.bus.remove_all_listeners()
                except Exception:
                    self.logger.warning(
                        "Listener cleanup failed for instance '%s'",
                        inst.app_config.instance_name,
                        exc_info=True,
                    )
                try:
                    # Goes straight to Scheduler.remove_all_jobs() rather than scanning the
                    # full registry by owner string — the per-app Scheduler already holds its
                    # owned jobs (including waiting, completed, and manual jobs that never
                    # touch the heap) in _jobs_by_name, and remove_all_jobs() is the same
                    # identity-checked, registry-aware path the normal shutdown uses
                    # (Scheduler.on_shutdown). A heap-only scan would miss those jobs and leak
                    # their entity-watch subscriptions.
                    #
                    # Also deregisters the removal callback, mirroring on_shutdown()'s second
                    # statement — remove_all_jobs() itself never does this (hassette/testing/_reset.py
                    # calls it on a Scheduler instance meant to be reused across tests, where
                    # deregistering would silently break future job removals on that instance).
                    # A failed-init instance is discarded, not reused: Scheduler.__init__
                    # registers this callback unconditionally, before on_initialize ever runs,
                    # so a failed instance always has one registered, and nothing here will
                    # reuse this Scheduler object afterward — skipping the deregister would
                    # leak the stale callback (and the Scheduler it closes over) in
                    # SchedulerService._removal_callbacks until/unless a future instance for
                    # the same owner_id happens to overwrite that dict entry.
                    await inst.scheduler.remove_all_jobs()
                    inst.scheduler.scheduler_service.deregister_removal_callback(inst.scheduler.owner_id)
                except Exception:
                    self.logger.warning(
                        "Job cleanup failed for instance '%s'",
                        inst.app_config.instance_name,
                        exc_info=True,
                    )
                try:
                    await inst.cache.close()
                except Exception:
                    self.logger.warning(
                        "Cache cleanup failed for instance '%s'",
                        inst.app_config.instance_name,
                        exc_info=True,
                    )
        except TimeoutError:
            self.logger.warning(
                "Cleanup timed out for failed instance '%s' — some listeners or jobs may leak until restart",
                inst.app_config.instance_name,
            )

    async def shutdown_instance(self, inst: "App[AppConfig]", instance_index: int | None = None) -> None:
        """Shutdown a single app instance.

        Args:
            inst: The app instance to shutdown
            instance_index: Instance index for correlation ID binding. When provided, app identity
                context vars are bound for the duration of the shutdown call so all log records
                emitted during on_shutdown carry app identity.
        """
        if instance_index is not None:
            structlog.contextvars.bind_contextvars(
                app_key=inst.app_config.app_key or None,
                instance_name=inst.app_config.instance_name,
                instance_index=instance_index,
            )
        try:
            start_time = timer()
            with anyio.fail_after(self.shutdown_timeout):
                await inst.shutdown()

            end_time = timer()
            if precisedelta is not None:
                friendly_time = precisedelta(end_time - start_time, minimum_unit="milliseconds")
            else:
                friendly_time = f"{end_time - start_time:.3f}s"
            self.logger.debug(
                "Stopped app '%s' '%s' in %s", inst.app_config.instance_name, inst.class_name, friendly_time
            )
            await self.emit_app_state_change(inst, status=STOPPED, previous_status=STOPPING)
        except Exception as exc:
            self.logger.error(
                "Failed to stop app '%s' after %s seconds:\n%s",
                inst.app_config.instance_name,
                self.shutdown_timeout,
                get_short_traceback(),
            )
            await self.emit_app_state_change(inst, status=FAILED, previous_status=STOPPING, exception=exc)
        finally:
            if instance_index is not None:
                structlog.contextvars.unbind_contextvars("app_key", "instance_name", "instance_index")

    async def shutdown_instances(
        self,
        instances: dict[int, "App[AppConfig]"],
    ) -> None:
        """Shutdown all provided app instances.

        Args:
            instances: Dict of index -> App to shutdown
        """
        if not instances:
            return

        self.logger.debug("Stopping %d app instances", len(instances))

        for idx, inst in instances.items():
            event = HassetteAppStateEvent.from_app(app=inst, status=STOPPING, previous_status=inst.status)
            await self.hassette.send_event(event)
            await self.shutdown_instance(inst, instance_index=idx)

    async def shutdown_all(self) -> None:
        """Shutdown all registered apps."""
        self.logger.debug("Shutting down all apps")

        for app_key in self.registry.app_keys():
            await self.shutdown_instances(self.registry.get_running_apps(app_key))

        self.registry.clear_all()

    async def emit_app_state_change(
        self,
        app: "App[AppConfig]",
        status: ResourceStatus,
        previous_status: ResourceStatus | None = None,
        exception: Exception | BaseException | None = None,
    ) -> None:
        """Emit an app state change event via Hassette's event system."""
        event = HassetteAppStateEvent.from_app(
            app=app, status=status, previous_status=previous_status, exception=exception
        )
        await self.hassette.send_event(event)

    @property
    def bootstrap_coordinator(self) -> "AppBootstrapCoordinator":
        return self.hassette.app_bootstrap_coordinator

    def _get_app_key_lock(self, app_key: str) -> asyncio.Lock:
        return self._app_key_locks.setdefault(app_key, asyncio.Lock())

    async def _admit_start(self, *, app_key: str, admission_mode: AppAdmissionMode) -> None:
        if admission_mode is AppAdmissionMode.WAIT_FOR_RELEASE:
            await self.bootstrap_coordinator.wait_released()
            return
        if self.bootstrap_coordinator.is_released():
            return
        raise AppBootstrapNotReleasedError(f"App {app_key!r} cannot start before bootstrap release")

    def _record_pre_release_reconciliation(
        self,
        *,
        original_apps_config: dict[str, "AppManifest"],
        current_apps_config: dict[str, "AppManifest"],
        changed_file_paths: frozenset[Path] | None,
    ) -> None:
        pending = self._pending_reconciliation

        if pending is None:
            # First deferred change since the queue was last taken: this call's own baseline
            # and paths become the queue's baseline and paths.
            merged_original = original_apps_config
            merged_paths = changed_file_paths
        elif changed_file_paths is None or pending.changed_paths is None:
            # Either this call or a previous one couldn't scope its paths, so the merged scope
            # degrades to "unknown" (None means "assume everything may have changed").
            merged_original = pending.original_apps_config
            merged_paths = None
        else:
            # Keep the original pre-existing baseline (the "before" snapshot from the first
            # deferred change), union the newly-touched paths onto the ones already queued.
            merged_original = pending.original_apps_config
            merged_paths = pending.changed_paths | changed_file_paths

        self._pending_reconciliation = PendingReconciliation(
            original_apps_config=merged_original,
            current_apps_config=current_apps_config,
            changed_paths=merged_paths,
        )

    def _take_pre_release_reconciliation(
        self,
    ) -> tuple[dict[str, "AppManifest"] | None, dict[str, "AppManifest"] | None, frozenset[Path] | None]:
        pending = self._pending_reconciliation
        self._pending_reconciliation = None
        if pending is None:
            return None, None, None
        return pending.original_apps_config, pending.current_apps_config, pending.changed_paths

    async def bootstrap_apps(self, *, admission_mode: AppAdmissionMode) -> None:
        """Initialize all configured and enabled apps, called at AppHandler startup.

        All declared dependencies are guaranteed ready by AppHandler's depends_on
        auto-wait before this method is invoked.
        """
        if not self.registry.manifests:
            self.logger.debug("No apps configured, skipping initialization")
            if admission_mode is AppAdmissionMode.WAIT_FOR_RELEASE:
                await self.bootstrap_coordinator.wait_released()
                await self._replay_pre_release_reconciliation_if_needed()
            return

        try:
            await self.resolve_only_apps()
            self.reconcile_blocked_apps()
            await self.persist_manifests()
            await self.start_apps(admission_mode=admission_mode)
            await self._replay_pre_release_reconciliation_if_needed()
            snapshot = self.registry.get_snapshot()
            if not snapshot.running_count and not snapshot.failed_count:
                self.logger.warning("No apps were initialized (all apps may be disabled)")
            else:
                self.logger.debug(
                    "Initialized %d apps successfully, %d failed to start",
                    snapshot.running_count,
                    snapshot.failed_count,
                )

            await self.hassette.send_event(
                HassetteSimpleEvent.from_topic(topic=Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED),
            )
        except Exception as exc:
            self.logger.exception("Failed to initialize apps")
            await handle_crash(self, exc)
            raise

    async def start_app(
        self,
        app_key: str,
        force_reload: bool = False,
        *,
        admission_mode: AppAdmissionMode = AppAdmissionMode.REJECT_IF_UNRELEASED,
    ) -> None:
        """Create instances for an app and await their initialization.

        Args:
            app_key: The app key to start
            force_reload: Whether to force-reload the app class from disk
        """
        app_manifest = self.registry.get_manifest(app_key)
        if not app_manifest:
            self.logger.debug("Skipping disabled or unknown app %s", app_key)
            return

        await self._admit_start(app_key=app_key, admission_mode=admission_mode)

        async with self._get_app_key_lock(app_key):
            # Re-fetch under the lock: _admit_start() can block indefinitely (WAIT_FOR_RELEASE
            # awaits AppBootstrapCoordinator's release latch), and a concurrent file-watcher
            # reconciliation can remove or replace this app's manifest while that wait is
            # parked. Acting on the pre-wait manifest would create instances for an app that
            # no longer exists (or no longer matches current config).
            app_manifest = self.registry.get_manifest(app_key)
            if not app_manifest:
                self.logger.debug("Skipping disabled or unknown app %s", app_key)
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
            self.factory.create_instances(app_key, app_manifest, force_reload=force_reload)
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

        instances = self.registry.get_running_apps(app_key)
        if instances:
            for inst in instances.values():
                event = HassetteAppStateEvent.from_app(app=inst, status=NOT_STARTED)
                await self.hassette.send_event(event)
            await self.initialize_instances(app_key, instances, app_manifest)

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

                app_manifest = self.registry.get_manifest(app_key)
                if not app_manifest:
                    self.logger.debug("Skipping disabled or unknown app %s", app_key)
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
        app_manifest = self.registry.get_manifest(app_key)
        if not app_manifest:
            self.logger.debug("Skipping disabled or unknown app %s", app_key)
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
        app_manifest = self.registry.get_manifest(app_key)
        if not app_manifest:
            self.logger.debug("Skipping disabled or unknown app %s", app_key)
            return

        await self._admit_start(app_key=app_key, admission_mode=admission_mode)

        try:
            async with self._get_app_key_lock(app_key):
                # Re-fetch under the lock — mirrors start_app()'s stale-manifest race guard.
                app_manifest = self.registry.get_manifest(app_key)
                if not app_manifest:
                    self.logger.debug("Skipping disabled or unknown app %s", app_key)
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

    def should_autostart(self, app_key: str) -> bool:
        """A new/not-yet-running app auto-starts only if its manifest allows it."""
        manifest = self.registry.get_manifest(app_key)
        return bool(manifest and manifest.autostart)

    def should_auto_reconcile(self, app_key: str) -> bool:
        """Already-running apps are always reconciled; dormant apps only if autostart."""
        return app_key in self.registry or self.should_autostart(app_key)

    async def start_apps(
        self,
        apps: set[str] | None = None,
        *,
        admission_mode: AppAdmissionMode = AppAdmissionMode.REJECT_IF_UNRELEASED,
    ) -> None:
        """Create initialization tasks for apps.

        Args:
            apps: Set of app keys to initialize. If None, initialize all autostart-enabled apps.
        """
        apps = apps if apps is not None else set(self.registry.autostart_manifests.keys())

        results = await asyncio.gather(
            *[self.start_app(app_key, admission_mode=admission_mode) for app_key in apps],
            return_exceptions=True,
        )

        # asyncio.CancelledError is a BaseException, not an Exception, so it is invisible to
        # the `isinstance(r, Exception)` filter below — asyncio.gather(return_exceptions=True)
        # collects it as an ordinary result instead of propagating it. Left unchecked, a
        # cancelled start_app() (e.g. shutdown firing while _admit_start() is parked) would be
        # silently dropped here, and bootstrap_apps() would proceed to emit
        # HASSETTE_EVENT_APP_LOAD_COMPLETED as if startup finished normally. Re-raise the first
        # one found so cancellation propagates to the caller instead.
        for result in results:
            if isinstance(result, asyncio.CancelledError):
                raise result

        exception_results = [r for r in results if isinstance(r, Exception)]
        for result in exception_results:
            self.logger.error("Error during app initialization: %s", result, exc_info=result)

    async def apply_changes(
        self,
        changes: ChangeSet,
        original_config: dict[str, "AppManifest"],
        current_config: dict[str, "AppManifest"],
    ) -> None:
        """Apply detected changes by stopping, reloading, or starting apps.

        Precondition: the four change buckets are disjoint, as guaranteed by
        ``AppChangeDetector.detect_changes`` (orphans are keys absent from the
        current config; reimport/reload/new are all keys present in it). Orphans
        are processed first; a key in both ``orphans`` and a reload bucket would
        be stopped and then skipped. Callers constructing a ``ChangeSet`` by hand
        (e.g. tests) must keep the buckets disjoint.

        Args:
            changes: The set of changes to apply
            original_config: The app manifests before this change (used to diff per-instance
                ``app_config`` entries for the ``reload_apps`` bucket — see below)
            current_config: The app manifests after this change
        """
        self.logger.debug("Applying app changes: %s", changes)

        # AppBlockedError from reload_app()/start_app()/_reload_app_or_changed_instances()
        # below is caught per app_key in every loop, even though it should be structurally
        # unreachable here: AppChangeDetector.detect_changes() filters every ChangeSet bucket
        # by only_apps before this method ever sees app_key, and
        # _fold_unblocked_apps_into_changes() only adds apps that were *just* unblocked. That
        # invariant spans three files and isn't enforced at this boundary, so if it's ever
        # violated, an uncaught raise here would abort the rest of this bucket and every
        # bucket after it — not just the one blocked app_key.
        for app_key in changes.orphans:
            self.logger.debug("Stopping orphaned app %s", app_key)
            await self.stop_app(app_key)

        for app_key in changes.reimport_apps:
            if not self.should_auto_reconcile(app_key):
                self.logger.debug("Skipping reimport of autostart=false app %s (not running)", app_key)
                continue

            self.logger.debug("Reloading app %s due to file change", app_key)
            try:
                await self.reload_app(app_key, force_reload=True)
            except AppBlockedError:
                self.logger.error("Skipping reimport of blocked app %s — this should not be reachable", app_key)

        for app_key in changes.reload_apps:
            if not self.should_auto_reconcile(app_key):
                self.logger.debug("Skipping reload of autostart=false app %s (not running)", app_key)
                continue

            try:
                await self._reload_app_or_changed_instances(app_key, original_config, current_config)
            except AppBlockedError:
                self.logger.error("Skipping reload of blocked app %s — this should not be reachable", app_key)

        for app_key in changes.new_apps:
            if not self.should_autostart(app_key):
                self.logger.debug("Skipping autostart of app %s (autostart=false)", app_key)
                continue

            self.logger.debug("Starting new app %s", app_key)
            try:
                await self.start_app(app_key)
            except AppBlockedError:
                self.logger.error("Skipping start of blocked app %s — this should not be reachable", app_key)

    async def _reload_app_or_changed_instances(
        self,
        app_key: str,
        original_config: dict[str, "AppManifest"],
        current_config: dict[str, "AppManifest"],
    ) -> None:
        """Reload only the instances whose ``app_config`` dict changed, or fall back to a full
        app-key reload when the app has no running instances (dormant), the instance list length
        changed, or a name collision would occur (see design doc "Data flow for selective restart").

        A missing entry on either side of ``original_config``/``current_config`` (should not
        happen for a key already in ``changes.reload_apps``, but config snapshots are caller-
        supplied) falls back to a full reload rather than raising.
        """
        # A dormant app (no running instances) that reaches here via should_auto_reconcile
        # (autostart just flipped to True) needs all instances created, not just the ones whose
        # app_config changed. The selective path only creates changed indices, permanently
        # leaving unchanged siblings unstarted.
        if app_key not in self.registry:
            self.logger.debug("App %s has no running instances - starting all via full reload", app_key)
            await self.reload_app(app_key)
            return

        old_manifest = original_config.get(app_key)
        new_manifest = current_config.get(app_key)
        if old_manifest is None or new_manifest is None:
            self.logger.debug("Reloading app %s due to config change", app_key)
            await self.reload_app(app_key)
            return

        old_instances = self.factory.normalize_configs(old_manifest.app_config)
        new_instances = self.factory.normalize_configs(new_manifest.app_config)

        if len(old_instances) != len(new_instances):
            self.logger.debug(
                "Instance count changed for app %s (%d -> %d) - reloading all instances",
                app_key,
                len(old_instances),
                len(new_instances),
            )
            await self.reload_app(app_key)
            return

        changed_indices = [i for i in range(len(new_instances)) if old_instances[i] != new_instances[i]]
        if not changed_indices:
            self.logger.debug("No per-instance config changes detected for app %s", app_key)
            return

        # A changed index can adopt an instance_name that an *unchanged* sibling still holds —
        # e.g. index 0's instance_name changes A -> B while index 1's instance_name stays B (see
        # PR #1687 review finding, filed against the stop-all/create-all fix above). Neither this
        # method's changed_indices computation nor _reload_changed_indices' batch reload ever
        # looks at indices outside the batch, so index 1 is never touched: after the batch
        # reload, index 0 (now "B") and index 1 (still "B") both exist and both derive the same
        # App.unique_name, permanently sharing one entry in the Bus/Scheduler owner-keyed
        # registries. instance_name uniqueness within one app_key's app_config is not enforced
        # anywhere at config-validation time (see config/classes.py's validate_app_config, which
        # only fills in a *missing* instance_name — it never checks for duplicates), so this
        # overlap is not something we can reject as an invalid config: the new config is valid on
        # its own, it only conflicts with the *currently running* old config during the
        # transition. Detect the overlap here and fall back to a full app reload, which stops
        # every instance (including untouched ones) before recreating any of them.
        changed_set = set(changed_indices)
        unchanged_names = {old_instances[i]["instance_name"] for i in range(len(old_instances)) if i not in changed_set}
        new_names_list = [new_instances[i]["instance_name"] for i in changed_set]
        new_names = set(new_names_list)
        overlap = unchanged_names & new_names
        if overlap:
            self.logger.debug(
                "Changed instance(s) of app %s would adopt instance_name(s) %s still held by an "
                "unchanged sibling instance - reloading all instances to avoid a name collision",
                app_key,
                sorted(overlap),
            )
            await self.reload_app(app_key)
            return

        # Two *changed* indices can also adopt the same new instance_name from each other --
        # e.g. index 0: a -> c, index 1: b -> c. No unchanged sibling holds "c", so the check
        # above sees no overlap, but _reload_changed_indices' create-all phase would still
        # create two live instances both deriving App.unique_name "c", the same permanent
        # owner-registry collision as the unchanged-sibling case. `new_names` (a set) silently
        # collapses such duplicates, so compare its length against the changed-index count
        # rather than checking membership.
        if len(new_names) != len(new_names_list):
            self.logger.debug(
                "Changed instance(s) of app %s would collide on a shared new instance_name - "
                "reloading all instances to avoid a name collision",
                app_key,
            )
            await self.reload_app(app_key)
            return

        await self._reload_changed_indices(app_key, changed_indices)

    async def _reload_changed_indices(self, app_key: str, changed_indices: list[int]) -> None:
        """Reload the given instance indices of ``app_key`` under one lock, stopping every
        affected index before creating any replacement.

        Extracted from ``_reload_app_or_changed_instances`` — see that method for the fallback
        cases (missing manifest, instance-count changed) that precede this batch reload.

        Split into a stop-all phase followed by a create-all phase (rather than reloading each
        index fully concurrently, stop-then-create) — see PR #1687 review finding. A batch that
        renames multiple instances can make a *new* instance take an ``instance_name`` (and
        therefore ``App.unique_name``/owner_id) still held by *another* instance in the same
        batch — e.g. index 0's ``instance_name`` changes ``A`` -> ``B`` while index 1's changes
        ``B`` -> ``C``. Bus/Scheduler owner registries (``BusService.router``,
        ``BusService._removal_callbacks``, the equivalent Scheduler structures) are keyed by that
        name string alone, not by ``(app_key, index)``. Interleaving each index's stop-then-create
        concurrently (the previous ``asyncio.gather`` over full per-index reloads) could let index
        0's new "B" register its listeners/jobs/removal-callback before index 1's old "B" finished
        tearing down — the old teardown would then rip out the new instance's freshly-registered
        state, since both are indistinguishable by owner_id alone. Stopping every affected index
        first (nothing new has been registered yet, so no create can collide with an in-flight
        stop) and only then creating replacements eliminates the interleaving hazard structurally,
        regardless of which names overlap or in which order — no overlap detection needed.
        """
        self.logger.debug("Reloading changed instance(s) %s of app %s", changed_indices, app_key)

        app_manifest = self.registry.get_manifest(app_key)
        if not app_manifest:
            self.logger.debug("Skipping disabled or unknown app %s", app_key)
            return

        valid_indices = [idx for idx in changed_indices if self._instance_index_in_range(app_key, idx, app_manifest)]
        if not valid_indices:
            return

        async def _create_one(idx: int) -> None:
            # Per-index try/except, mirroring the previous _reload_one() guard — a failure at
            # one index must not abort the remaining indices in this batch, nor the caller's
            # loop over other app_keys in apply_changes() (see code review finding).
            try:
                await self._create_instance_unlocked(app_key, idx, app_manifest)
            except Exception:
                self.logger.error("Failed to reload instance %d of app %s:\n%s", idx, app_key, get_short_traceback())

        # Single lock acquisition for the whole batch — reload_instance() also acquires this
        # lock, so calling it per-index here (instead of the unlocked body) would deadlock on
        # the non-reentrant asyncio.Lock on the second index. Instances of the same app_key
        # share no mutable state (each owns its own Bus/Scheduler/StateManager/Api/AsyncCache —
        # see design.md "Dependencies and Assumptions"), so each phase runs concurrently within
        # itself. This bounds the lock's hold time at roughly two instances' timeouts (one stop
        # phase plus one create phase) instead of N — looser than the previous single-phase
        # claim of "one instance's timeout," but still far short of a fully sequential N-instance
        # bound, and necessary to close the name-collision race described above.
        #
        # _stop_instance_unlocked already wraps its own body in try/except (see its docstring),
        # so a stop failure at one index is isolated and logged there without needing a guard
        # here too — unlike the create phase below, which needs its own per-index try/except.
        async with self._get_app_key_lock(app_key):
            await asyncio.gather(*(self._stop_instance_unlocked(app_key, idx) for idx in valid_indices))
            await asyncio.gather(*(_create_one(idx) for idx in valid_indices))

    async def handle_change_event(
        self,
        changed_file_paths: typing.Annotated[
            frozenset[Path] | None, A.get_path("payload.data.changed_file_paths")
        ] = None,
    ) -> None:
        """Handle changes detected by the file watcher.

        Called as a Bus event handler with DI-injected ``changed_file_paths``. Serialized by
        ``self._change_event_lock`` — this listener runs in the bus's ``parallel`` execution
        mode (framework tier), so two file-watcher events dispatched close together would
        otherwise run this method concurrently and race on ``_pending_reconciliation`` and on
        ``refresh_config()``'s in-place mutation of ``self.registry.manifests``.
        """
        async with self._change_event_lock:
            self.logger.debug("Handling app change event for files: %s", changed_file_paths)

            original_apps_config, current_apps_config = await self.refresh_config()
            await self.resolve_only_apps()

            if self.bootstrap_coordinator.is_released() and self._pending_reconciliation is not None:
                # A pre-release change is still queued. Fold it into this diff's baseline so the
                # comparison spans everything since before release, then clear the queue — otherwise
                # bootstrap's later replay would apply that stale snapshot on top of a config it no
                # longer matches (see integration review finding on stale pre-release replay).
                self.logger.debug("Merging queued pre-release reconciliation into post-release change")
                pending_original, _, pending_paths = self._take_pre_release_reconciliation()
                if pending_original is not None:
                    original_apps_config = pending_original
                    if pending_paths is None or changed_file_paths is None:
                        changed_file_paths = None
                    else:
                        changed_file_paths |= pending_paths

            changes = self.change_detector.detect_changes(
                original_apps_config, current_apps_config, changed_file_paths, only_apps=self.registry.only_apps
            )

            changes = self._fold_unblocked_apps_into_changes(changes)

            if not changes.has_changes:
                # A manifest can differ (e.g. display_name, autostart) without requiring any
                # lifecycle action. That still means the persisted manifest is out of sync with
                # what a connected dashboard last fetched -- refresh_config() already persisted
                # it above -- so broadcast the same refetch signal apply_changes() would trigger
                # below, without running apply_changes() itself. Gated on bootstrap release like
                # every other broadcast here: while unreleased there's no running app state for a
                # dashboard to have fetched yet, and the load-completed broadcast at the end of
                # bootstrap covers it once release opens.
                if changes.has_any_change and self.bootstrap_coordinator.is_released():
                    self.logger.debug(
                        "%s changed, metadata-only manifest changes detected - %s", changed_file_paths, changes
                    )
                    await self.hassette.send_event(
                        HassetteSimpleEvent.from_topic(topic=Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED),
                    )
                else:
                    self.logger.debug("%s changed but no app changes detected", changed_file_paths)
                return

            if not self.bootstrap_coordinator.is_released():
                self.logger.debug("Deferring app reconciliation until bootstrap release opens")
                self._record_pre_release_reconciliation(
                    original_apps_config=original_apps_config,
                    current_apps_config=current_apps_config,
                    changed_file_paths=changed_file_paths,
                )
                return

            self.logger.debug("%s changed, app changes detected - %s", changed_file_paths, changes)

            await self.apply_changes(changes, original_apps_config, current_apps_config)

            await self.hassette.send_event(
                HassetteSimpleEvent.from_topic(topic=Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED),
            )

    async def refresh_config(self) -> tuple[dict[str, "AppManifest"], dict[str, "AppManifest"]]:
        """Reload the configuration and return (original_apps_config, current_apps_config)."""
        # Filter only by enabled status, NOT by the exclusive-app filter, so both configs are comparable
        original_apps_config = {k: deepcopy(v) for k, v in self.registry.manifests.items() if v.enabled}

        # Reinitialize config to pick up changes.
        # https://docs.pydantic.dev/latest/concepts/pydantic_settings/#in-place-reloading
        try:
            self.hassette.config.reload()
        except Exception as exc:
            self.logger.exception("Failed to reload configuration: %s", exc)

        self.set_apps_configs(self.hassette.config.apps.manifests)
        await self.persist_manifests()
        current_apps_config = {k: deepcopy(v) for k, v in self.registry.manifests.items() if v.enabled}

        return original_apps_config, current_apps_config

    async def _replay_pre_release_reconciliation_if_needed(self) -> None:
        # Shares _pending_reconciliation state with handle_change_event(), which serializes on
        # this same lock — without it, a file-watcher event arriving as bootstrap replays could
        # race the take/clear of that state.
        async with self._change_event_lock:
            if self._pending_reconciliation is None:
                return

            original_apps_config, current_apps_config, changed_file_paths = self._take_pre_release_reconciliation()
            if original_apps_config is None or current_apps_config is None:
                return
            self.logger.debug("Replaying deferred app reconciliation after bootstrap release opens")
            await self.resolve_only_apps()

            changes = self.change_detector.detect_changes(
                original_apps_config, current_apps_config, changed_file_paths, only_apps=self.registry.only_apps
            )

            changes = self._fold_unblocked_apps_into_changes(changes)

            if not changes.has_changes:
                # Mirrors handle_change_event()'s no-lifecycle-change branch: a metadata-only
                # change (e.g. display_name) queued before release still needs its broadcast
                # once release opens, even though there's nothing for apply_changes() to do.
                if changes.has_any_change:
                    self.logger.debug("Deferred reconciliation produced metadata-only changes - %s", changes)
                    await self.hassette.send_event(
                        HassetteSimpleEvent.from_topic(topic=Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED),
                    )
                else:
                    self.logger.debug("Deferred app reconciliation produced no changes")
                return

            await self.apply_changes(changes, original_apps_config, current_apps_config)

    async def persist_manifests(self) -> None:
        """Upsert all current manifests into the ``app_manifests`` DB table concurrently.

        Called from ``bootstrap_apps()`` (initial load, after ``set_apps_configs()`` and before
        ``start_apps()``) and ``refresh_config()`` (hot reload, after ``set_apps_configs()`` and
        before ``apply_changes()`` in the caller). Manifests are upserted concurrently via
        ``asyncio.gather(return_exceptions=True)``, matching ``start_apps()`` — a sequential loop
        here would serialize up to ``N * MANIFEST_UPSERT_TIMEOUT_SECONDS`` onto every boot and
        hot-reload if the DB is merely slow rather than down. Each upsert still has its own
        ``anyio.fail_after()`` timeout and try/except (see ``persist_manifest()``), so one app's
        failure never affects another's, and a failed write is self-correcting on the next
        successful write. This must never block app startup or a config reload.
        """
        manifests = self.registry.manifests
        self.logger.debug("Persisting %d manifest(s) to the app_manifests table", len(manifests))
        await asyncio.gather(
            *(self.persist_manifest(app_key, manifest) for app_key, manifest in manifests.items()),
            return_exceptions=True,
        )
        self.logger.debug("Finished persisting manifests")

    async def persist_manifest(self, app_key: str, manifest: "AppManifest") -> None:
        """Upsert a single manifest, isolating its own timeout and failure from the batch.

        Never raises — a timeout or a genuine write failure is logged and swallowed so that
        one app's persistence problem can't affect any other app's, whether called from the
        ``persist_manifests()`` batch or directly for a single app.
        """
        try:
            with anyio.fail_after(MANIFEST_UPSERT_TIMEOUT_SECONDS):
                await self.hassette.command_executor.upsert_app_manifest(manifest)
        except TimeoutError:
            # This timeout only cancels our wait on `DatabaseService`'s write queue — the
            # single-writer worker task isn't inside this scope, so the write may still land
            # moments after we give up on it. Unlike a genuine write failure, "timed out"
            # doesn't mean the write didn't happen.
            self.logger.warning(
                "Timed out waiting for manifest persist for app '%s' — write may still complete "
                "in the background; dashboard metadata may be stale until the next successful write",
                app_key,
            )
        except Exception:
            self.logger.warning(
                "Failed to persist manifest for app '%s' — dashboard metadata may be stale "
                "until the next successful write",
                app_key,
                exc_info=True,
            )

    def set_apps_configs(self, apps_config: dict[str, "AppManifest"]) -> None:
        """Set the apps configuration.

        Args:
            apps_config: The new apps configuration.
        """
        self.logger.debug("Setting apps configuration")
        self.registry.set_manifests(deepcopy(apps_config))
        self.registry.set_only_apps(())  # reset the filter, it is recomputed on next initialize

        self.logger.debug(
            "Found %d apps in configuration: %s", len(self.registry.manifests), list(self.registry.manifests.keys())
        )

    async def resolve_only_apps(self) -> None:
        """Apply the ``--app`` exclusive-app filter, if given."""
        requested = set(self.hassette.config.only_apps)
        if not requested:
            return

        known = requested & set(self.registry.enabled_manifests)
        unknown = requested - known
        if unknown:
            self.logger.error(
                "No enabled app matches --app key(s) %s; enabled apps are: %s",
                ", ".join(sorted(unknown)),
                ", ".join(sorted(self.registry.enabled_manifests)) or "(none)",
            )
        if known:
            self.logger.warning("Running only %s, skipping all other apps", ", ".join(sorted(known)))

        # Deliberately `requested`, not `known` — narrowing to `known` would turn an all-typo
        # request into an empty filter, which means "no filter" and starts every app.
        self.registry.set_only_apps(requested)

    def _fold_unblocked_apps_into_changes(self, changes: ChangeSet) -> ChangeSet:
        """Reconcile blocked-app state and fold any newly-unblocked apps into ``changes`` as starts.

        Shared by ``handle_change_event()`` and ``_replay_pre_release_reconciliation_if_needed()``,
        both of which reconcile the ``--app`` filter's blocked-app state against the current
        registry before applying detected changes.
        """
        unblocked = self.reconcile_blocked_apps()
        to_start = unblocked - set(self.registry.app_keys()) - changes.new_apps - changes.reimport_apps
        if not to_start:
            return changes
        self.logger.debug("Starting previously-blocked apps: %s", to_start)
        return ChangeSet(
            orphans=changes.orphans,
            new_apps=changes.new_apps | frozenset(to_start),
            reimport_apps=changes.reimport_apps,
            reload_apps=changes.reload_apps - to_start,
            metadata_apps=changes.metadata_apps,
        )

    def reconcile_blocked_apps(self) -> set[str]:
        """Synchronize blocked state with the current exclusive-app filter.

        Returns:
            App keys that were unblocked (previously blocked but no longer).
        """
        previously_blocked = self.registry.unblock_apps(BlockReason.ONLY_APP)

        currently_blocked: set[str] = set()
        if self.registry.only_apps:
            for app_key in self.registry.enabled_manifests:
                if app_key not in self.registry.only_apps:
                    self.registry.block_app(app_key, BlockReason.ONLY_APP)
                    currently_blocked.add(app_key)

        return previously_blocked - currently_blocked

    def collect_live_listener_ids(self, app_key: str, instances: "dict[int, App[AppConfig]]") -> set[int]:
        """Collect listener db_ids registered by all instances.

        Registration is synchronous with the DB — db_ids are set before on_initialize() returns.
        """
        live_listener_ids: set[int] = set()
        for inst in instances.values():
            try:
                for listener in inst.bus.get_listeners():
                    if listener.db_id is not None:
                        live_listener_ids.add(listener.db_id)
            except Exception:
                self.logger.warning(
                    "Failed to collect listener IDs from app '%s' instance — proceeding with partial set",
                    app_key,
                )
        return live_listener_ids

    def merge_router_listener_ids(
        self,
        app_key: str,
        instances: "dict[int, App[AppConfig]]",
        bus_service: "BusService",
        live_listener_ids: set[int],
    ) -> set[int]:
        """Union in listener db_ids the Router knows are active.

        Avoids retiring rows for mid-session active handlers that ``collect_live_listener_ids``
        may have missed. Returns a new set rather than mutating ``live_listener_ids``.
        """
        try:
            router = bus_service.router
            router_ids: set[int] = set()
            for inst in instances.values():
                for listener in router.get_listeners_by_owner(inst.bus.owner_id):
                    if listener.db_id is not None:
                        router_ids.add(listener.db_id)
            return live_listener_ids | router_ids
        except Exception:
            self.logger.warning(
                "Router safety guard failed for app '%s' — proceeding with collected live IDs only",
                app_key,
            )
            return live_listener_ids

    def collect_live_job_ids(self, app_key: str, instances: "dict[int, App[AppConfig]]") -> list[int]:
        """Collect scheduled-job db_ids registered by all instances."""
        live_job_ids: list[int] = []
        for inst in instances.values():
            try:
                live_job_ids.extend(inst.scheduler.get_job_db_ids())
            except Exception:
                self.logger.warning(
                    "Failed to collect job IDs from app '%s' instance — proceeding with partial set",
                    app_key,
                )
        return live_job_ids

    def resolve_session_id(self, app_key: str) -> int | None:
        """Resolve the current session ID for the once=True cleanup guard.

        Returns None (degraded mode) if the session ID is unavailable — once=True
        cleanup is skipped and deferred to the next restart.
        """
        try:
            return self.hassette.session_id
        except Exception:
            self.logger.warning(
                "session_id unavailable for app '%s' — reconciliation running in degraded mode; "
                "once=True cleanup skipped (deferred to next restart)",
                app_key,
            )
            return None

    async def reconcile_app_registrations(
        self,
        app_key: str,
        instances: "dict[int, App[AppConfig]]",
        instance_index: int | None = None,
    ) -> None:
        """Run post-ready reconciliation for an app after all instances are initialized.

        Awaits pending DB registrations, collects live IDs from all instances,
        applies the Router safety guard, then calls reconcile_registrations.
        Failure is non-fatal — logs a warning and allows the app to continue.

        Args:
            app_key: The app key to reconcile.
            instances: Dict of instance index -> App (may include failed instances).
            instance_index: When provided, scopes reconciliation to this instance only, so
                restarting one instance does not retire sibling instances' rows. When None
                (default), reconciliation is app_key-scoped only — unchanged behavior.
        """
        try:
            bus_service = self.hassette.bus_service

            live_listener_ids = self.collect_live_listener_ids(app_key, instances)
            live_listener_ids = self.merge_router_listener_ids(app_key, instances, bus_service, live_listener_ids)
            live_job_ids = self.collect_live_job_ids(app_key, instances)
            session_id = self.resolve_session_id(app_key)

            await self.hassette.command_executor.reconcile_registrations(
                app_key,
                list(live_listener_ids),
                live_job_ids,
                session_id=session_id,
                instance_index=instance_index,
            )
            self.logger.debug("Post-ready reconciliation complete for app '%s'", app_key)
        except Exception:
            self.logger.warning(
                "Post-ready reconciliation failed for app '%s' — reconciliation rolled back; "
                "stale rows (including once=True cleanup) may remain until next restart",
                app_key,
                exc_info=True,
            )
