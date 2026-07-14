"""AppLifecycleService — owns app lifecycle orchestration and change handling."""

import asyncio
import typing
from copy import deepcopy
from pathlib import Path
from timeit import default_timer as timer

import anyio
import structlog.contextvars

import hassette.event_handling.accessors as A
from hassette.core.app_change_detector import AppChangeDetector, ChangeSet
from hassette.core.app_factory import AppFactory
from hassette.events.hassette import HassetteAppStateEvent, HassetteSimpleEvent
from hassette.exceptions import InvalidInheritanceError, UndefinedUserConfigError
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
    from hassette.core.app_registry import AppRegistry
    from hassette.core.bus_service import BusService

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
    ) -> None:
        """Initialize all instances for an app key.

        Records failures directly to the registry. After all instances are
        initialized, awaits pending DB registrations and runs post-ready
        reconciliation to retire stale rows from previous sessions.

        Args:
            app_key: The app key
            instances: Dict of index -> App to initialize
            manifest: The app manifest
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
        await self.reconcile_app_registrations(app_key, instances)

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
                    await self.hassette.scheduler_service.remove_jobs_by_owner(inst.scheduler.owner_id)
                except Exception:
                    self.logger.warning(
                        "Job cleanup failed for instance '%s'",
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
            await self.shutdown_instances(self.registry.get_apps_by_key(app_key))

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

    async def bootstrap_apps(self) -> None:
        """Initialize all configured and enabled apps, called at AppHandler startup.

        All declared dependencies are guaranteed ready by AppHandler's depends_on
        auto-wait before this method is invoked.
        """
        if not self.registry.manifests:
            self.logger.debug("No apps configured, skipping initialization")
            return

        try:
            await self.resolve_only_app()
            self.reconcile_blocked_apps()
            await self.start_apps()
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

    async def start_app(self, app_key: str, force_reload: bool = False) -> None:
        """Create instances for an app and await their initialization.

        Args:
            app_key: The app key to start
            force_reload: Whether to force-reload the app class from disk
        """
        app_manifest = self.registry.get_manifest(app_key)
        if not app_manifest:
            self.logger.debug("Skipping disabled or unknown app %s", app_key)
            return

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

        instances = self.registry.get_apps_by_key(app_key)
        if instances:
            for inst in instances.values():
                event = HassetteAppStateEvent.from_app(app=inst, status=NOT_STARTED)
                await self.hassette.send_event(event)
            await self.initialize_instances(app_key, instances, app_manifest)

    async def stop_app(self, app_key: str) -> None:
        """Stop and remove all instances for a given app key.

        Args:
            app_key: The app key to stop
        """
        try:
            instances = self.registry.unregister_app(app_key)
            if not instances:
                self.logger.warning("Cannot stop app %s, not found", app_key)
                return

            await self.shutdown_instances(instances)
        except Exception:
            self.logger.error("Failed to stop app %s:\n%s", app_key, get_short_traceback())

    async def reload_app(self, app_key: str, force_reload: bool = False) -> None:
        """Stop and reinitialize a single app by key (based on current config).

        Args:
            app_key: The app key to reload
            force_reload: Whether to force-reload the app class from disk
        """
        self.logger.debug("Reloading app %s", app_key)
        try:
            await self.stop_app(app_key)
            await self.start_app(app_key, force_reload=force_reload)
        except Exception:
            self.logger.error("Failed to reload app %s:\n%s", app_key, get_short_traceback())

    def should_autostart(self, app_key: str) -> bool:
        """A new/not-yet-running app auto-starts only if its manifest allows it."""
        manifest = self.registry.get_manifest(app_key)
        return bool(manifest and manifest.autostart)

    def should_auto_reconcile(self, app_key: str) -> bool:
        """Already-running apps are always reconciled; dormant apps only if autostart."""
        return app_key in self.registry or self.should_autostart(app_key)

    async def start_apps(self, apps: set[str] | None = None) -> None:
        """Create initialization tasks for apps.

        Args:
            apps: Set of app keys to initialize. If None, initialize all autostart-enabled apps.
        """
        apps = apps if apps is not None else set(self.registry.autostart_manifests.keys())

        results = await asyncio.gather(*[self.start_app(app_key) for app_key in apps], return_exceptions=True)
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

        Called as a Bus event handler with DI-injected ``changed_file_paths``.
        """
        self.logger.debug("Handling app change event for files: %s", changed_file_paths)

        original_apps_config, curr_apps_config = await self.refresh_config()
        await self.resolve_only_app(changed_file_paths)

        changes = self.change_detector.detect_changes(
            original_apps_config, curr_apps_config, changed_file_paths, only_app=self.registry.only_app
        )

        # Reconcile blocked apps — start any that were unblocked
        unblocked = self.reconcile_blocked_apps()
        to_start = unblocked - set(self.registry.app_keys()) - changes.new_apps - changes.reimport_apps
        if to_start:
            self.logger.debug("Starting previously-blocked apps: %s", to_start)
            changes = ChangeSet(
                orphans=changes.orphans,
                new_apps=changes.new_apps | frozenset(to_start),
                reimport_apps=changes.reimport_apps,
                reload_apps=changes.reload_apps - to_start,
            )

        if not changes.has_changes:
            self.logger.debug("%s changed but no app changes detected", changed_file_paths)
            return

        self.logger.debug("%s changed, app changes detected - %s", changed_file_paths, changes)

        await self.apply_changes(changes)

        await self.hassette.send_event(
            HassetteSimpleEvent.from_topic(topic=Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED),
        )

    async def refresh_config(self) -> tuple[dict[str, "AppManifest"], dict[str, "AppManifest"]]:
        """Reload the configuration and return (original_apps_config, current_apps_config)."""
        # Filter only by enabled status, NOT by only_app filter, so both configs are comparable
        original_apps_config = {k: deepcopy(v) for k, v in self.registry.manifests.items() if v.enabled}

        # Reinitialize config to pick up changes.
        # https://docs.pydantic.dev/latest/concepts/pydantic_settings/#in-place-reloading
        try:
            self.hassette.config.reload()
        except Exception as exc:
            self.logger.exception("Failed to reload configuration: %s", exc)

        self.set_apps_configs(self.hassette.config.apps.manifests)
        curr_apps_config = {k: deepcopy(v) for k, v in self.registry.manifests.items() if v.enabled}

        return original_apps_config, curr_apps_config

    def set_apps_configs(self, apps_config: dict[str, "AppManifest"]) -> None:
        """Set the apps configuration.

        Args:
            apps_config: The new apps configuration.
        """
        self.logger.debug("Setting apps configuration")
        self.registry.set_manifests(deepcopy(apps_config))
        self.registry.set_only_app(None)  # reset only_app, will be recomputed on next initialize

        self.logger.debug(
            "Found %d apps in configuration: %s", len(self.registry.manifests), list(self.registry.manifests.keys())
        )

    async def resolve_only_app(self, changed_file_paths: frozenset[Path] | None = None) -> None:
        """Determine if any app is marked as only and update only app filter accordingly."""
        only_apps: list[str] = []
        changed = changed_file_paths or frozenset()

        for app_manifest in self.registry.active_manifests.values():
            try:
                force_reload = app_manifest.full_path in changed
                if self.factory.check_only_app_decorator(app_manifest, force_reload=force_reload):
                    only_apps.append(app_manifest.app_key)
            except (UndefinedUserConfigError, InvalidInheritanceError):
                self.logger.error(
                    "Failed to load app '%s' due to bad configuration - check previous logs for details",
                    app_manifest.display_name,
                )

        if not only_apps:
            self.registry.set_only_app(None)
            return

        if not self.hassette.config.dev_mode:
            if not self.hassette.config.allow_only_app_in_prod:
                self.logger.warning("Disallowing use of `only_app` decorator in production mode")
                self.registry.set_only_app(None)
                return
            self.logger.warning("Allowing use of `only_app` decorator in production mode due to config")

        if len(only_apps) > 1:
            keys = ", ".join(app for app in only_apps)
            raise RuntimeError(f"Multiple apps marked as only: {keys}")

        self.registry.set_only_app(only_apps[0])
        self.logger.warning("App %s is marked as only, skipping all others", self.registry.only_app)

    def reconcile_blocked_apps(self) -> set[str]:
        """Synchronize blocked state with current only_app value.

        Returns:
            App keys that were unblocked (previously blocked but no longer).
        """
        previously_blocked = self.registry.unblock_apps(BlockReason.ONLY_APP)

        currently_blocked: set[str] = set()
        if self.registry.only_app:
            for app_key in self.registry.enabled_manifests:
                if app_key != self.registry.only_app:
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
    ) -> None:
        """Run post-ready reconciliation for an app after all instances are initialized.

        Awaits pending DB registrations, collects live IDs from all instances,
        applies the Router safety guard, then calls reconcile_registrations.
        Failure is non-fatal — logs a warning and allows the app to continue.

        Args:
            app_key: The app key to reconcile.
            instances: Dict of instance index -> App (may include failed instances).
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
            )
            self.logger.debug("Post-ready reconciliation complete for app '%s'", app_key)
        except Exception:
            self.logger.warning(
                "Post-ready reconciliation failed for app '%s' — reconciliation rolled back; "
                "stale rows (including once=True cleanup) may remain until next restart",
                app_key,
                exc_info=True,
            )
