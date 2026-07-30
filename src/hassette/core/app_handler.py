"""AppHandler — thin coordinator facade over AppLifecycleService.

Owns the AppRegistry and delegates all lifecycle operations to
AppLifecycleService (a Resource child).
"""

import asyncio
import typing
from typing import ClassVar

from hassette.bus import Bus
from hassette.core.app_bootstrap_coordinator import AppBootstrapCoordinator
from hassette.core.app_change_detector import ChangeSet
from hassette.core.app_lifecycle_service import AppAdmissionMode, AppLifecycleService
from hassette.core.app_registry import AppRegistry
from hassette.resources.base import Resource
from hassette.resources.lifecycle import mark_not_ready, mark_ready
from hassette.schemas.app_snapshots import AppStatusSnapshot
from hassette.types import Topic
from hassette.types.types import LOG_LEVEL_TYPE

if typing.TYPE_CHECKING:
    from hassette import AppConfig, Hassette
    from hassette.app.app import App


class AppHandler(Resource):
    """Manages the lifecycle of apps in Hassette.

    Acts as a thin facade coordinating:
    - AppRegistry: State tracking and queries
    - AppLifecycleService: Lifecycle orchestration, change detection, factory
    """

    depends_on: ClassVar[list[type[Resource]]] = [AppBootstrapCoordinator]

    # Per-instance restart instead of full app-key restart (#796)

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
        self.lifecycle.set_apps_configs(hassette.config.apps.manifests)
        self._bootstrap_task: asyncio.Task[None] | None = None
        self._bootstrap_completed = asyncio.Event()

    def get_status_snapshot(self) -> AppStatusSnapshot:
        """Get immutable snapshot of all app states for web UI."""
        return self.registry.get_snapshot()

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        return self.hassette.config.logging.app_handler

    def get(self, app_key: str, index: int = 0) -> "App[AppConfig] | None":
        """Get a specific app instance if running."""
        return self.registry.get(app_key, index)

    def all(self) -> list["App[AppConfig]"]:
        """All running app instances."""
        return self.registry.all_apps()

    async def on_initialize(self) -> None:
        """Set up file-watcher subscription.

        The bootstrap coordinator is guaranteed wired by depends_on auto-wait.
        Readiness is deferred to after_initialize once app bootstrap completes.
        """
        if self.hassette.config.dev_mode or self.hassette.config.allow_reload_in_prod:
            if self.hassette.config.allow_reload_in_prod:
                self.logger.warning("Allowing app reloads in production mode due to config")
            self.logger.debug("Watching for app changes...")
            await self.bus.on(
                topic=str(Topic.HASSETTE_EVENT_FILE_WATCHER),
                handler=self.lifecycle.handle_change_event,
                name="hassette.app_handler.handle_change_event",
            )
        else:
            self.logger.debug("Not watching for app changes, dev_mode is disabled")

    async def after_initialize(self) -> None:
        """Schedule app bootstrap, then signal readiness.

        The bootstrap coordinator is guaranteed wired by depends_on auto-wait before
        on_initialize() runs. App bootstrap itself runs in background work so the
        finite startup wave can complete even while Home Assistant remains unavailable.
        """
        self.logger.debug("Scheduling app bootstrap")
        self._bootstrap_task = self.task_bucket.spawn(
            self.bootstrap_apps(admission_mode=AppAdmissionMode.WAIT_FOR_RELEASE),
            name="app_handler:bootstrap_apps",
        )
        mark_ready(self, reason="app handler wired")

    async def bootstrap_apps(self, *, admission_mode: AppAdmissionMode = AppAdmissionMode.WAIT_FOR_RELEASE) -> None:
        """Bootstrap apps and record completion — delegates to the lifecycle service.

        This is the one entrypoint that both the normal startup path (spawned as a
        background task above) and test-reset helpers must use to re-bootstrap apps.
        Calling ``lifecycle.bootstrap_apps()`` directly would bypass ``_bootstrap_completed``
        bookkeeping, creating a second bootstrap path that can drift from this one.
        """
        await self.lifecycle.bootstrap_apps(admission_mode=admission_mode)
        self._bootstrap_completed.set()

    def has_bootstrapped(self) -> bool:
        return self._bootstrap_completed.is_set()

    async def on_shutdown(self) -> None:
        """Shutdown all app instances gracefully."""
        self.logger.debug("Stopping '%s' %s", self.class_name, self.role)
        mark_not_ready(self, reason="shutting-down")
        if self._bootstrap_task is not None:
            self._bootstrap_task.cancel()
            await asyncio.gather(self._bootstrap_task, return_exceptions=True)
            self._bootstrap_task = None
        await self.lifecycle.shutdown_all()

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
