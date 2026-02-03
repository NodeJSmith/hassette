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
from hassette.events.hassette import HassetteSimpleEvent
from hassette.exceptions import InvalidInheritanceError, UndefinedUserConfigError
from hassette.resources.base import Resource
from hassette.types import Topic
from hassette.types.enums import ResourceStatus
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

    @classmethod
    def create(cls, hassette: "Hassette"):
        inst = cls(hassette, parent=hassette)

        # Initialize components
        inst.registry = AppRegistry()
        inst.factory = AppFactory(hassette, inst.registry)
        inst.change_detector = AppChangeDetector()
        inst.set_apps_configs(hassette.config.app_manifests)
        inst.lifecycle = AppLifecycleManager(hassette, inst.registry)

        # Event bus for status events
        inst.bus = inst.add_child(Bus)

        return inst

    # --- Public API ---

    @property
    def apps(self) -> dict[str, dict[int, App["AppConfig"]]]:
        """Running apps - delegates to registry."""
        return self.registry.apps

    @property
    def failed_apps(self) -> dict[str, list[tuple[int, Exception]]]:
        """Apps we could not start/failed to start - delegates to registry."""
        return self.registry.failed_apps

    @property
    def active_apps_config(self) -> dict[str, "AppManifest"]:
        """Apps that are enabled."""
        return self.registry.active_apps_config

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

        self.bus.remove_all_listeners()
        await self.lifecycle.shutdown_all()

    def get(self, app_key: str, index: int = 0) -> "App[AppConfig] | None":
        """Get a specific app instance if running."""
        return self.registry.apps.get(app_key, {}).get(index)

    def all(self) -> list["App[AppConfig]"]:
        """All running app instances."""
        return [inst for group in self.registry.apps.values() for inst in group.values()]

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
            await self.start_apps()
            if not self.registry.apps:
                self.logger.warning("No apps were initialized successfully")
            else:
                success_count = sum(
                    len([a for a in v.values() if a.status == ResourceStatus.RUNNING])
                    for v in self.registry.apps.values()
                )
                fail_count = sum(len(v) for v in self.registry.failed_apps.values())
                self.logger.debug("Initialized %d apps successfully, %d failed to start", success_count, fail_count)

            await self.hassette.send_event(
                Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED,
                HassetteSimpleEvent.create_event(topic=Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED),
            )
        except Exception as e:
            self.logger.exception("Failed to initialize apps")
            await self.handle_crash(e)
            raise

    async def _resolve_only_app(self) -> None:
        """Determine if any app is marked as only and update only app filter accordingly."""
        only_apps: list[str] = []

        for app_manifest in self.active_apps_config.values():
            try:
                if self.factory.check_only_app_decorator(app_manifest):
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

    async def refresh_config(self) -> tuple[dict[str, "AppManifest"], dict[str, "AppManifest"]]:
        """Reload the configuration and return (original_apps_config, current_apps_config)."""
        original_apps_config = deepcopy(self.active_apps_config)

        # Reinitialize config to pick up changes.
        # https://docs.pydantic.dev/latest/concepts/pydantic_settings/#in-place-reloading
        try:
            self.hassette.config.reload()
        except Exception as e:
            self.logger.exception("Failed to reload configuration: %s", e)

        self.set_apps_configs(self.hassette.config.app_manifests)
        curr_apps_config = deepcopy(self.active_apps_config)

        return original_apps_config, curr_apps_config

    async def handle_change_event(
        self,
        changed_file_path: typing.Annotated[Path | None, A.get_path("payload.data.changed_file_path")] = None,
    ) -> None:
        """Handle changes detected by the watcher."""

        # note: refresh_config will also update the only_app filter
        original_apps_config, curr_apps_config = await self.refresh_config()

        changes = self.change_detector.detect_changes(original_apps_config, curr_apps_config, changed_file_path)
        self.logger.debug("App changes detected - %s", changes)

        await self.apply_changes(changes)

        await self.hassette.send_event(
            Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED,
            HassetteSimpleEvent.create_event(topic=Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED),
        )

    async def start_apps(self, apps: set[str] | None = None) -> None:
        """Create initialization tasks for apps. If apps is None, initialize all enabled apps."""

        apps = apps if apps is not None else set(self.registry.active_apps_config.keys())

        results = await asyncio.gather(*[self.start_app(app_key) for app_key in apps], return_exceptions=True)
        exception_results = [r for r in results if isinstance(r, Exception)]
        for result in exception_results:
            self.logger.exception("Error during app initialization: %s", result)

    async def start_app(self, app_key: str, force_reload: bool = False) -> None:
        app_manifest = self.registry.active_apps_config.get(app_key)
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

        instances = self.registry.apps.get(app_key, {})
        if instances:
            await self.task_bucket.spawn(self.lifecycle.initialize_instances(app_key, instances, app_manifest))

    async def stop_app(self, app_key: str) -> None:
        """Stop and remove all instances for a given app_name."""
        try:
            instances = self.registry.unregister_app(app_key)
            if not instances:
                self.logger.warning("Cannot stop app %s, not found", app_key)
                return

            await self.lifecycle.shutdown_instances(instances, app_key, with_cleanup=False)
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
