"""AppHandler — thin coordinator facade over AppLifecycleService.

Owns the AppRegistry and delegates all lifecycle operations to
AppLifecycleService (a Resource child).
"""

import typing
from logging import getLogger
from typing import ClassVar

from hassette.bus import Bus
from hassette.core.api_resource import ApiResource
from hassette.core.app_change_detector import ChangeSet
from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.core.app_registry import AppRegistry, AppStatusSnapshot
from hassette.core.bus_service import BusService
from hassette.core.scheduler_service import SchedulerService
from hassette.core.state_proxy import StateProxy
from hassette.core.websocket_service import WebsocketService
from hassette.resources.base import Resource
from hassette.types import Topic
from hassette.types.types import LOG_LEVEL_TYPE

if typing.TYPE_CHECKING:
    from hassette import AppConfig, Hassette
    from hassette.app.app import App

LOGGER = getLogger(__name__)


class AppHandler(Resource):
    """Manages the lifecycle of apps in Hassette.

    Acts as a thin facade coordinating:
    - AppRegistry: State tracking and queries
    - AppLifecycleService: Lifecycle orchestration, change detection, factory
    """

    # CommandExecutor is not listed: bootstrap_apps() fires registrations that
    # flow through CommandExecutor, but CommandExecutor's internal wait_for_ready
    # guards protect those calls.  AppHandler does not call CommandExecutor directly.
    depends_on: ClassVar[list[type[Resource]]] = [
        WebsocketService,
        ApiResource,
        BusService,
        SchedulerService,
        StateProxy,
    ]

    # TODO: handle stopping/starting individual app instances, instead of all apps of a class/key
    # no need to restart app index 2 if only app index 0 changed, etc.

    registry: AppRegistry
    """Registry for tracking app state."""

    lifecycle: AppLifecycleService
    """Service owning lifecycle orchestration, change detection, and factory."""

    bus: Bus

    def __init__(self, hassette: "Hassette", *, parent: Resource | None = None) -> None:
        super().__init__(hassette, parent=parent)

        self.bus = self.add_child(Bus)
        self.registry = AppRegistry()
        self.lifecycle = self.add_child(AppLifecycleService, registry=self.registry)
        self.lifecycle.set_apps_configs(hassette.config.app_manifests)

    # --- Public API (thin delegation) ---

    @property
    def apps(self) -> dict[str, dict[int, "App[AppConfig]"]]:
        """Running apps - delegates to registry."""
        return self.registry.apps

    def get_status_snapshot(self) -> AppStatusSnapshot:
        """Get immutable snapshot of all app states for web UI."""
        return self.registry.get_snapshot()

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        """Return the log level from the config for this resource."""
        return self.hassette.config.app_handler_log_level

    def get(self, app_key: str, index: int = 0) -> "App[AppConfig] | None":
        """Get a specific app instance if running."""
        return self.registry.get(app_key, index)

    def all(self) -> list["App[AppConfig]"]:
        """All running app instances."""
        return self.registry.all_apps()

    # --- Lifecycle hooks ---

    async def on_initialize(self) -> None:
        """Set up file-watcher subscription and signal readiness.

        All declared dependencies (WebsocketService, ApiResource, BusService,
        SchedulerService, StateProxy) are guaranteed ready by depends_on auto-wait.
        """
        if self.hassette.config.dev_mode or self.hassette.config.allow_reload_in_prod:
            if self.hassette.config.allow_reload_in_prod:
                self.logger.warning("Allowing app reloads in production mode due to config")
            self.logger.debug("Watching for app changes...")
            self.bus.on(
                topic=str(Topic.HASSETTE_EVENT_FILE_WATCHER),
                handler=self.lifecycle.handle_change_event,
                name="hassette.app_handler.handle_change_event",
            )
        else:
            self.logger.debug("Not watching for app changes, dev_mode is disabled")

        self.mark_ready(reason="initialized")

    async def after_initialize(self) -> None:
        """Spawn app bootstrap.

        All declared dependencies are guaranteed ready by depends_on auto-wait before
        on_initialize() runs. bootstrap_apps runs in AppHandler's task_bucket; individual
        app initializations are spawned into AppLifecycleService's task_bucket
        (child Resource, shut down before parent).
        """
        self.logger.debug("Scheduling app initialization")
        self.task_bucket.spawn(self.lifecycle.bootstrap_apps())

    async def on_shutdown(self) -> None:
        """Shutdown all app instances gracefully."""
        self.logger.debug("Stopping '%s' %s", self.class_name, self.role)
        self.mark_not_ready(reason="shutting-down")
        await self.lifecycle.shutdown_all()

    # --- Delegated operations ---

    async def start_app(self, app_key: str, force_reload: bool = False) -> None:
        """Start an app by key — delegates to lifecycle service."""
        await self.lifecycle.start_app(app_key, force_reload=force_reload)

    async def stop_app(self, app_key: str) -> None:
        """Stop an app by key — delegates to lifecycle service."""
        await self.lifecycle.stop_app(app_key)

    async def reload_app(self, app_key: str, force_reload: bool = False) -> None:
        """Reload an app by key — delegates to lifecycle service."""
        await self.lifecycle.reload_app(app_key, force_reload=force_reload)

    async def apply_changes(self, changes: ChangeSet) -> None:
        """Apply detected changes — delegates to lifecycle service."""
        await self.lifecycle.apply_changes(changes)
