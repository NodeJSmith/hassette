import asyncio
import typing
from copy import deepcopy
from logging import getLogger
from pathlib import Path

import hassette.event_handling.accessors as A
from hassette.app.app import App
from hassette.bus import Bus
from hassette.core.app_change_detector import AppChangeDetector, ChangeSet
from hassette.core.app_factory import AppFactory
from hassette.core.app_lifecycle import AppLifecycleManager
from hassette.core.app_registry import AppRegistry, AppStatusSnapshot
from hassette.events.hassette import HassetteAppStateEvent, HassetteSimpleEvent
from hassette.exceptions import InvalidInheritanceError, UndefinedUserConfigError
from hassette.logging_ import get_log_capture_handler
from hassette.resources.base import Resource
from hassette.types import ResourceStatus, Topic
from hassette.types.enums import BlockReason
from hassette.utils.exception_utils import get_short_traceback

if typing.TYPE_CHECKING:
    from hassette import AppConfig, Hassette
    from hassette.config.classes import AppManifest

LOGGER = getLogger(__name__)


class AppHandler(Resource):
    """Manages the lifecycle of apps in Hassette.

    Acts as a facade coordinating:
    - AppRegistry: State tracking and queries
    - AppFactory: Instance creation
    - AppLifecycleManager: Init/shutdown orchestration
    - AppChangeDetector: Change detection
    """

    # TODO: handle stopping/starting individual app instances, instead of all apps of a class/key
    # no need to restart app index 2 if only app index 0 changed, etc.

    registry: AppRegistry
    """Registry for tracking app state."""

    factory: AppFactory
    """Factory for creating app instances."""

    lifecycle: AppLifecycleManager
    """Lifecycle manager for init/shutdown orchestration."""

    change_detector: AppChangeDetector
    """Detector for configuration changes."""

    bus: Bus
    """Event bus for inter-service communication."""

    def __init__(self, hassette: "Hassette", *, parent: Resource | None = None) -> None:
        super().__init__(hassette, parent=parent)

        # Initialize components
        self.registry = AppRegistry()
        self.factory = AppFactory(hassette, self.registry)
        self.change_detector = AppChangeDetector()
        self.set_apps_configs(hassette.config.app_manifests)
        self.lifecycle = AppLifecycleManager(hassette, self.registry)

        self.registry.logger.setLevel(self.config_log_level)
        self.factory.logger.setLevel(self.config_log_level)
        self.lifecycle.logger.setLevel(self.config_log_level)
        self.change_detector.logger.setLevel(self.config_log_level)

        # Event bus for status events
        self.bus = self.add_child(Bus)

    # --- Public API ---

    @property
    def apps(self) -> dict[str, dict[int, App["AppConfig"]]]:
        """Running apps - delegates to registry."""
        return self.registry.apps

    def get_status_snapshot(self) -> AppStatusSnapshot:
        """Get immutable snapshot of all app states for web UI."""
        return self.registry.get_snapshot()

    @property
    def config_log_level(self):
        """Return the log level from the config for this resource."""
        return self.hassette.config.app_handler_log_level

    def set_apps_configs(self, apps_config: dict[str, "AppManifest"]) -> None:
        """Set the apps configuration.

        Args:
            apps_config: The new apps configuration.
        """
        self.logger.debug("Setting apps configuration")
        self.registry.set_manifests(deepcopy(apps_config))
        self._update_only_app_filter(None)  # reset only_app, will be recomputed on next initialize

        self.logger.debug(
            "Found %d apps in configuration: %s", len(self.registry.manifests), list(self.registry.manifests.keys())
        )

    async def on_initialize(self) -> None:
        """Start handler and initialize configured apps."""
        if self.hassette.config.dev_mode or self.hassette.config.allow_reload_in_prod:
            if self.hassette.config.allow_reload_in_prod:
                self.logger.warning("Allowing app reloads in production mode due to config")
            self.logger.debug("Watching for app changes...")
            self.bus.on(topic=Topic.HASSETTE_EVENT_FILE_WATCHER, handler=self.handle_change_event)
        else:
            self.logger.debug("Not watching for app changes, dev_mode is disabled")

        await self.hassette.wait_for_ready(self.hassette._websocket_service)
        self.mark_ready("initialized")

    async def after_initialize(self) -> None:
        self.logger.debug("Scheduling app initialization")
        self.task_bucket.spawn(self.bootstrap_apps())

    async def on_shutdown(self) -> None:
        """Shutdown all app instances gracefully."""
        self.logger.debug("Stopping '%s' %s", self.class_name, self.role)
        self.mark_not_ready(reason="shutting-down")

        await self.bus.remove_all_listeners()
        await self.lifecycle.shutdown_all()

    def get(self, app_key: str, index: int = 0) -> "App[AppConfig] | None":
        """Get a specific app instance if running."""
        return self.registry.get(app_key, index)

    def all(self) -> list["App[AppConfig]"]:
        """All running app instances."""
        return self.registry.all_apps()

    async def bootstrap_apps(self) -> None:
        """Initialize all configured and enabled apps, called at AppHandler startup."""

        if not self.registry.manifests:
            self.logger.debug("No apps configured, skipping initialization")
            return

        if not await self.hassette.wait_for_ready(
            [
                self.hassette._websocket_service,
                self.hassette._api_service,
                self.hassette._bus_service,
                self.hassette._scheduler_service,
                self.hassette._state_proxy,
            ]
        ):
            self.logger.warning("Dependencies never became ready; skipping app startup")
            return

        try:
            await self._resolve_only_app()
            self._reconcile_blocked_apps()
            await self.start_apps()
            snapshot = self.get_status_snapshot()
            if not snapshot.running_count and not snapshot.failed_count:
                self.logger.warning("No apps were initialized (all apps may be disabled)")
            else:
                self.logger.debug(
                    "Initialized %d apps successfully, %d failed to start",
                    snapshot.running_count,
                    snapshot.failed_count,
                )

            await self.hassette.send_event(
                Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED,
                HassetteSimpleEvent.create_event(topic=Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED),
            )
        except Exception as e:
            self.logger.exception("Failed to initialize apps")
            await self.handle_crash(e)
            raise

    async def _resolve_only_app(self, changed_file_paths: frozenset[Path] | None = None) -> None:
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
            self._update_only_app_filter(None)
            return

        if not self.hassette.config.dev_mode:
            if not self.hassette.config.allow_only_app_in_prod:
                self.logger.warning("Disallowing use of `only_app` decorator in production mode")
                self._update_only_app_filter(None)
                return
            self.logger.warning("Allowing use of `only_app` decorator in production mode due to config")

        if len(only_apps) > 1:
            keys = ", ".join(app for app in only_apps)
            raise RuntimeError(f"Multiple apps marked as only: {keys}")

        self._update_only_app_filter(only_apps[0])
        self.logger.warning("App %s is marked as only, skipping all others", self.registry.only_app)

    def _update_only_app_filter(self, app_key: str | None) -> None:
        """Update the only_app filter in registry and change detector."""
        self.registry.set_only_app(app_key)
        self.change_detector.set_only_app_filter(app_key)

    def _reconcile_blocked_apps(self) -> set[str]:
        """Synchronize blocked state with current only_app value.

        Returns app_keys that were unblocked (previously blocked but no longer).
        """
        previously_blocked = self.registry.unblock_apps(BlockReason.ONLY_APP)

        currently_blocked: set[str] = set()
        if self.registry.only_app:
            for app_key in self.registry.enabled_manifests:
                if app_key != self.registry.only_app:
                    self.registry.block_app(app_key, BlockReason.ONLY_APP)
                    currently_blocked.add(app_key)

        return previously_blocked - currently_blocked

    async def refresh_config(self) -> tuple[dict[str, "AppManifest"], dict[str, "AppManifest"]]:
        """Reload the configuration and return (original_apps_config, current_apps_config)."""
        # Filter only by enabled status, NOT by only_app filter, so both configs are comparable
        original_apps_config = {k: deepcopy(v) for k, v in self.registry.manifests.items() if v.enabled}

        # Reinitialize config to pick up changes.
        # https://docs.pydantic.dev/latest/concepts/pydantic_settings/#in-place-reloading
        try:
            self.hassette.config.reload()
        except Exception as e:
            self.logger.exception("Failed to reload configuration: %s", e)

        self.set_apps_configs(self.hassette.config.app_manifests)
        curr_apps_config = {k: deepcopy(v) for k, v in self.registry.manifests.items() if v.enabled}

        return original_apps_config, curr_apps_config

    async def handle_change_event(
        self,
        changed_file_paths: typing.Annotated[
            frozenset[Path] | None, A.get_path("payload.data.changed_file_paths")
        ] = None,
    ) -> None:
        """Handle changes detected by the watcher."""
        self.logger.debug("Handling app change event for files: %s", changed_file_paths)

        original_apps_config, curr_apps_config = await self.refresh_config()
        await self._resolve_only_app(changed_file_paths)

        changes = self.change_detector.detect_changes(original_apps_config, curr_apps_config, changed_file_paths)

        # Reconcile blocked apps — start any that were unblocked
        unblocked = self._reconcile_blocked_apps()
        to_start = unblocked - set(self.registry.apps.keys()) - changes.new_apps - changes.reimport_apps
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
            Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED,
            HassetteSimpleEvent.create_event(topic=Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED),
        )

    async def start_apps(self, apps: set[str] | None = None) -> None:
        """Create initialization tasks for apps. If apps is None, initialize all enabled apps."""

        apps = apps if apps is not None else set(self.registry.active_manifests.keys())

        results = await asyncio.gather(*[self.start_app(app_key) for app_key in apps], return_exceptions=True)
        exception_results = [r for r in results if isinstance(r, Exception)]
        for result in exception_results:
            self.logger.error("Error during app initialization: %s", result, exc_info=result)

    async def start_app(self, app_key: str, force_reload: bool = False) -> None:
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
            handler = get_log_capture_handler()
            for inst in instances.values():
                if handler:
                    handler.register_app_logger(inst.logger.name, app_key)
                event = HassetteAppStateEvent.from_data(app=inst, status=ResourceStatus.NOT_STARTED)
                await self.hassette.send_event(Topic.HASSETTE_EVENT_APP_STATE_CHANGED, event)
            await self.task_bucket.spawn(self.lifecycle.initialize_instances(app_key, instances, app_manifest))

    async def stop_app(self, app_key: str) -> None:
        """Stop and remove all instances for a given app_name."""
        try:
            instances = self.registry.unregister_app(app_key)
            if not instances:
                self.logger.warning("Cannot stop app %s, not found", app_key)
                return

            await self.lifecycle.shutdown_instances(instances)
        except Exception:
            self.logger.error("Failed to stop app %s:\n%s", app_key, get_short_traceback())

    async def reload_app(self, app_key: str, force_reload: bool = False) -> None:
        """Stop and reinitialize a single app by key (based on current config)."""
        self.logger.debug("Reloading app %s", app_key)
        try:
            await self.stop_app(app_key)
            await self.start_app(app_key, force_reload=force_reload)
        except Exception:
            self.logger.error("Failed to reload app %s:\n%s", app_key, get_short_traceback())

    async def apply_changes(self, changes: ChangeSet) -> None:
        """Apply detected changes."""

        self.logger.debug("Applying app changes: %s", changes)

        for app_key in changes.orphans:
            self.logger.debug("Stopping orphaned app %s", app_key)
            await self.stop_app(app_key)

        for app_key in changes.reimport_apps:
            self.logger.debug("Reloading app %s due to file change", app_key)
            await self.reload_app(app_key, force_reload=True)

        for app_key in changes.reload_apps:
            self.logger.debug("Reloading app %s due to config change", app_key)
            await self.reload_app(app_key)

        for app_key in changes.new_apps:
            self.logger.debug("Starting new app %s", app_key)
            await self.start_app(app_key)
