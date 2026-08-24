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
from hassette.exceptions import AppBootstrapNotReleasedError, InvalidInheritanceError, UndefinedUserConfigError
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
                    get_short_traceback(INIT_FAILURE_TRACEBACK_LIMIT),
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
                    get_short_traceback(INIT_FAILURE_TRACEBACK_LIMIT),
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
                    # Goes straight to Scheduler.remove_all_jobs() rather than
                    # SchedulerService.remove_jobs_by_owner() — the per-app Scheduler already
                    # holds its owned jobs (including waiting, completed, and manual jobs that
                    # never touch the heap) in _jobs_by_name, and remove_all_jobs() is the
                    # same identity-checked, registry-aware path the normal shutdown uses
                    # (Scheduler.on_shutdown). remove_jobs_by_owner()'s heap-only scan would
                    # miss those jobs and leak their entity-watch subscriptions.
                    #
                    # Also deregisters the removal callback, mirroring on_shutdown()'s second
                    # statement — remove_all_jobs() itself never does this (test_utils/reset.py
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
        except Exception:
            self.logger.error("Failed to reload app %s:\n%s", app_key, get_short_traceback())

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

    async def apply_changes(self, changes: ChangeSet) -> None:
        """Apply detected changes by stopping, reloading, or starting apps.

        Precondition: the four change buckets are disjoint, as guaranteed by
        ``AppChangeDetector.detect_changes`` (orphans are keys absent from the
        current config; reimport/reload/new are all keys present in it). Orphans
        are processed first; a key in both ``orphans`` and a reload bucket would
        be stopped and then skipped. Callers constructing a ``ChangeSet`` by hand
        (e.g. tests) must keep the buckets disjoint.

        Args:
            changes: The set of changes to apply
        """
        self.logger.debug("Applying app changes: %s", changes)

        for app_key in changes.orphans:
            self.logger.debug("Stopping orphaned app %s", app_key)
            await self.stop_app(app_key)

        for app_key in changes.reimport_apps:
            if self.should_auto_reconcile(app_key):
                self.logger.debug("Reloading app %s due to file change", app_key)
                await self.reload_app(app_key, force_reload=True)
            else:
                self.logger.debug("Skipping reimport of autostart=false app %s (not running)", app_key)

        for app_key in changes.reload_apps:
            if self.should_auto_reconcile(app_key):
                self.logger.debug("Reloading app %s due to config change", app_key)
                await self.reload_app(app_key)
            else:
                self.logger.debug("Skipping reload of autostart=false app %s (not running)", app_key)

        for app_key in changes.new_apps:
            if self.should_autostart(app_key):
                self.logger.debug("Starting new app %s", app_key)
                await self.start_app(app_key)
            else:
                self.logger.debug("Skipping autostart of app %s (autostart=false)", app_key)

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

            await self.apply_changes(changes)

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
                self.logger.debug("Deferred app reconciliation produced no changes")
                return

            await self.apply_changes(changes)

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
