"""AppHandler — thin coordinator facade over AppLifecycleService.

Owns the AppRegistry and delegates all lifecycle operations to
AppLifecycleService (a Resource child).
"""

import asyncio
import typing
from typing import ClassVar

import structlog
from hassette_wire import LogLevel

from hassette.bus import Bus
from hassette.core.app_bootstrap_coordinator import AppBootstrapCoordinator
from hassette.core.app_change_detector import ChangeSet
from hassette.core.app_lifecycle_common import AppAdmissionMode
from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.core.app_registry import AppRegistry
from hassette.resources.base import Resource
from hassette.resources.lifecycle import mark_not_ready, mark_ready
from hassette.resources.service import Service
from hassette.resources.shutdown_outcome import ShutdownOutcome, merge_outcomes
from hassette.schemas.app_config_shape import configured_instance_names
from hassette.schemas.app_snapshots import AppStatusSnapshot
from hassette.types import Topic

if typing.TYPE_CHECKING:
    from hassette import AppConfig, Hassette
    from hassette.app.app import App
    from hassette.config.classes import AppManifest
    from hassette.schemas.app_outcomes import InstanceOutcome


class AppHandler(Service):
    """Manages the lifecycle of apps in Hassette.

    Acts as a thin facade coordinating:
    - AppRegistry: State tracking and queries
    - AppLifecycleService: Lifecycle orchestration, change detection, factory

    A required service whose ``serve()`` runs app bootstrap, so a failed bootstrap is reported and
    ends the process like any other required service's failure (spec 134 D14, D17).
    """

    depends_on: ClassVar[list[type[Resource]]] = [AppBootstrapCoordinator]
    required: ClassVar[bool] = True

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
        self._bootstrap_completed = asyncio.Event()

    def get_status_snapshot(self) -> AppStatusSnapshot:
        """Get immutable snapshot of all app states for web UI."""
        return self.registry.get_snapshot()

    @property
    def config_log_level(self) -> LogLevel:
        """Return the configured log level for the app handler (``logging.app_handler``)."""
        return self.hassette.config.logging.app_handler

    def get(self, app_key: str, *, instance_name: str | None = None) -> "App[AppConfig] | None":
        """Get a running app instance by name; with no name, the first running one in config order."""
        return self.registry.get(app_key, instance_name)

    def all(self) -> list["App[AppConfig]"]:
        """All running app instances."""
        return self.registry.all_apps()

    async def on_initialize(self) -> None:
        """Set up file-watcher subscription.

        The bootstrap coordinator is guaranteed wired by depends_on auto-wait.
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
        """Signal readiness before app bootstrap runs.

        Bootstrap waits on Home Assistant (the bootstrap coordinator's release), which no startup wave
        may, so readiness means "wired", not "apps started", and ``serve()`` runs bootstrap after the
        wave has moved on.
        """
        mark_ready(self, reason="app handler wired")

    async def serve(self) -> None:
        """Bootstrap apps, then wait for shutdown. A failed bootstrap raises, which ends the process."""
        await self.bootstrap_apps(admission_mode=AppAdmissionMode.WAIT_FOR_RELEASE)
        await self.shutdown_event.wait()

    async def bootstrap_apps(self, *, admission_mode: AppAdmissionMode = AppAdmissionMode.WAIT_FOR_RELEASE) -> None:
        """Bootstrap apps and record completion — delegates to the lifecycle service.

        This is the one entrypoint that both the normal startup path (``serve()``) and test-reset
        helpers must use to re-bootstrap apps.
        Calling ``lifecycle.bootstrap_apps()`` directly would bypass ``_bootstrap_completed``
        bookkeeping, creating a second bootstrap path that can drift from this one.
        """
        await self.lifecycle.bootstrap_apps(admission_mode=admission_mode)
        self._bootstrap_completed.set()

    def has_bootstrapped(self) -> bool:
        """Return whether a :meth:`bootstrap_apps` run has completed."""
        return self._bootstrap_completed.is_set()

    async def on_shutdown(self) -> None:
        """Mark not ready; bootstrap stopped with the serve task, and the registry apps stop in the child stage."""
        self.logger.debug("Stopping '%s' %s", self.class_name, self.role)
        mark_not_ready(self, reason="shutting-down")

    async def _shutdown_children(self) -> ShutdownOutcome:
        """Stop every registry app concurrently, then this handler's own children.

        Apps stop through the same instance-stop path runtime stops use, each under its own entry
        deadline shortened to this attempt's deadline, so an app whose hooks run long costs no other app
        its ``on_shutdown``. Their shutdown outcomes merge into this handler's own. Orchestration, not a
        hook: nothing bounds it but the deadline, and only the root walks away from it.
        """
        apps_outcome = await self.lifecycle.shutdown_all(deadline=self._shutdown_deadline)
        children_outcome = await super()._shutdown_children()
        return merge_outcomes(apps_outcome, children_outcome)

    def _force_terminal(self) -> None:
        """Also force-terminate the registry apps, which are not children of this handler.

        The root's stop-stage ERROR names only this handler, so the apps whose stop hadn't finished get
        their own ERROR here. A runtime stop or reload already in flight is reached too: its instances stay
        registered until their teardown finishes.
        """
        instances = [
            inst for app_key in self.registry.app_keys() for inst in self.registry.get_running_apps(app_key).values()
        ]
        unfinished = [inst for inst in instances if not inst.shutdown_completed]
        if unfinished:
            self.logger.error(
                "Force-terminating apps whose stop hadn't finished: %s",
                ", ".join(f"{inst.app_config.instance_name} ({inst.class_name})" for inst in unfinished),
            )
        for inst in instances:
            inst._force_terminal()
        super()._force_terminal()

    def set_debug_capture(self, app_key: str, instance_name: str | None, enabled: bool) -> dict[str, bool]:
        """Turn debug capture on or off for one instance, or app-wide, and return each targeted name's state.

        App-wide ``on`` captures every configured instance; app-wide ``off`` ends capture for every name under
        ``app_key``, configured or not. Every targeted running instance has its levels re-applied at once, which
        also repairs an instance whose flag drifted from the registry; a stopped one gets them when it starts,
        since ``AppFactory`` passes the flag in at construction. Each instance whose state changed gets a WARNING
        attributed to it.

        Takes no lifecycle lock and must never await (spec 148 D6): app construction and registration are
        synchronous, so on one event loop a concurrent build sees the registry either before or after this whole
        change, never partway.

        Args:
            app_key: The app to act on; the caller has checked that it is known.
            instance_name: One instance, or ``None`` for every instance.
            enabled: Whether capture should be on.

        Returns:
            Each targeted instance name, in display order, mapped to whether capture is now on for it.
        """
        registry = self.registry
        manifest = registry.get_manifest(app_key)
        configured = configured_instance_names(manifest.app_config) if manifest is not None else []
        if instance_name is not None:
            targets = [instance_name]
        elif enabled:
            targets = configured
        else:
            # App-wide off also reaches captured names that left the config, before the next start prunes them.
            targets = [*configured, *sorted(registry.debug_captured_names(app_key).difference(configured))]

        changed = {name for name in targets if registry.is_debug_captured(app_key, name) != enabled}
        registry.set_debug_capture(app_key, targets, enabled)

        for name in targets:
            # Every live target is re-applied, not only the changed ones: the App's flag is a mirror, so a repeat
            # request repairs one that drifted from the registry. Re-applying is idempotent.
            if (app := registry.get(app_key, name)) is not None:
                app.set_debug_capture(enabled)
            if name not in changed:
                continue
            with structlog.contextvars.bound_contextvars(app_key=app_key, instance_name=name):
                if enabled:
                    self.logger.warning(
                        "Debug capture on for %s/%s: its own and its framework loggers log at DEBUG. "
                        "It ends at `hassette app debug %s off` or a hassette restart.",
                        app_key,
                        name,
                        app_key,
                    )
                else:
                    self.logger.warning("Debug capture off for %s/%s: levels are back to config", app_key, name)

        return {name: registry.is_debug_captured(app_key, name) for name in targets}

    def is_action_in_progress(self, app_key: str) -> bool:
        """Whether an action on ``app_key`` is running — delegates to lifecycle service."""
        return self.lifecycle.is_action_in_progress(app_key)

    async def start_app(self, app_key: str, force_reload: bool = False) -> "tuple[InstanceOutcome, ...]":
        """Start an app by key — delegates to lifecycle service."""
        return await self.lifecycle.start_app(app_key, force_reload=force_reload)

    async def stop_app(self, app_key: str) -> "tuple[InstanceOutcome, ...]":
        """Stop an app by key — delegates to lifecycle service."""
        return await self.lifecycle.stop_app(app_key)

    async def reload_app(self, app_key: str, force_reload: bool = False) -> "tuple[InstanceOutcome, ...]":
        """Reload an app by key — delegates to lifecycle service."""
        return await self.lifecycle.reload_app(app_key, force_reload=force_reload)

    async def reload_instance(
        self, app_key: str, instance_name: str, force_reload: bool = False
    ) -> "tuple[InstanceOutcome, ...]":
        """Reload a single instance by key and name — delegates to lifecycle service."""
        return await self.lifecycle.reload_instance(app_key, instance_name, force_reload=force_reload)

    async def stop_instance(self, app_key: str, instance_name: str) -> "tuple[InstanceOutcome, ...]":
        """Stop a single instance by key and name — delegates to lifecycle service."""
        return await self.lifecycle.stop_instance(app_key, instance_name)

    async def start_instance(self, app_key: str, instance_name: str) -> "tuple[InstanceOutcome, ...]":
        """Start a single instance by key and name — delegates to lifecycle service."""
        return await self.lifecycle.start_instance(app_key, instance_name)

    async def apply_changes(
        self,
        changes: ChangeSet,
        original_config: dict[str, "AppManifest"],
        current_config: dict[str, "AppManifest"],
    ) -> None:
        """Apply detected changes — delegates to lifecycle service."""
        await self.lifecycle.apply_changes(changes, original_config, current_config)
