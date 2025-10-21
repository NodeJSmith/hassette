import asyncio
import typing
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from logging import getLogger
from pathlib import Path
from timeit import default_timer as timer
from typing import Any

import anyio
from humanize import precisedelta

from hassette.core.resources.app.app import App
from hassette.core.resources.base import Resource
from hassette.core.resources.bus.bus import Bus
from hassette.enums import ResourceStatus
from hassette.events.hassette import HassetteEmptyPayload
from hassette.exceptions import InvalidInheritanceError, UndefinedUserConfigError
from hassette.topics import (
    HASSETTE_EVENT_APP_LOAD_COMPLETED,
    HASSETTE_EVENT_FILE_WATCHER,
    HASSETTE_EVENT_SERVICE_STATUS,
    HASSETTE_EVENT_WEBSOCKET_STATUS,
)
from hassette.utils.app_utils import load_app_class

if typing.TYPE_CHECKING:
    from hassette import AppConfig, Hassette
    from hassette.config.app_manifest import AppManifest
    from hassette.events import Event, HassetteFileWatcherEvent

LOGGER = getLogger(__name__)
LOADED_CLASSES: "dict[tuple[str, str], type[App[AppConfig]]]" = {}


@dataclass(slots=True)
class AppChangeSet:
    removed_apps: set[str] = field(default_factory=set)
    removed_instances: dict[str, set[int]] = field(default_factory=dict)
    new_apps: set[str] = field(default_factory=set)
    new_instances: dict[str, set[int]] = field(default_factory=dict)
    reimport_apps: set[str] = field(default_factory=set)
    reload_apps: set[str] = field(default_factory=set)
    reload_instances: dict[str, set[int]] = field(default_factory=dict)


class _AppHandler(Resource):  # pyright: ignore[reportUnusedClass]
    """Manages the lifecycle of apps in Hassette.

    - Deterministic storage: apps[app_name][index] -> App
    - Tracks per-app failures in failed_apps for observability
    """

    # TODO:
    # need to separate startup of app handler from initialization of apps
    # so that we can start the app handler, then the API, then initialize apps
    # because apps may want to use the API during startup
    # could trigger on websocket connected event, with a once=True handler?

    # TODO: handle stopping/starting individual app instances, instead of all apps of a class/key
    # no need to restart app index 2 if only app index 0 changed, etc.

    # TODO: clean this class up - it likely needs to be split into smaller pieces

    apps_config: dict[str, "AppManifest"]
    """Copy of Hassette's config apps"""

    apps: dict[str, dict[int, App["AppConfig"]]]
    """Running apps"""

    failed_apps: dict[str, list[tuple[int, Exception]]]
    """Apps we could not start/failed to start"""

    only_app: str | None
    """If set, only this app will be started (the one marked as only)"""

    bus: Bus
    """Event bus for inter-service communication."""

    @classmethod
    def create(cls, hassette: "Hassette"):
        inst = cls(hassette, parent=hassette)
        inst.apps_config = {}
        inst.set_apps_configs(hassette.config.apps)
        inst.only_app = None
        inst.apps = defaultdict(dict)
        inst.failed_apps = defaultdict(list)
        inst.bus = inst.add_child(Bus)
        inst._dependency_ready: dict[str, bool] = {}
        inst._initialization_scheduled = False
        inst._api_unique_name: str | None = None
        return inst

    @property
    def config_log_level(self):
        """Return the log level from the config for this resource."""
        return self.hassette.config.app_handler_log_level

    def set_apps_configs(self, apps_config: dict[str, "AppManifest"]) -> None:
        """Set the apps configuration.

        Args:
            apps_config (dict[str, AppManifest]): The new apps configuration.
        """
        self.logger.debug("Setting apps configuration")
        self.apps_config = deepcopy(apps_config)
        self.only_app = None  # reset only_app, will be recomputed on next initialize

        self.logger.debug("Found %d apps in configuration: %s", len(self.apps_config), list(self.apps_config.keys()))

    @property
    def active_apps_config(self) -> dict[str, "AppManifest"]:
        """Apps that are enabled."""
        enabled_apps = {k: v for k, v in self.apps_config.items() if v.enabled}
        if self.only_app:
            enabled_apps = {k: v for k, v in enabled_apps.items() if k == self.only_app}
        return enabled_apps

    async def on_initialize(self) -> None:
        """Start handler and initialize configured apps."""
        self._setup_watchers()
        self._setup_dependency_listeners()
        self.mark_ready("initialized")
        self._check_initial_boot_conditions()

    async def after_initialize(self) -> None:
        self.logger.debug("Evaluating app initialization dependencies")
        self._check_initial_boot_conditions()

    def _setup_watchers(self) -> None:
        if self.hassette.config.dev_mode or self.hassette.config.allow_reload_in_prod:
            if self.hassette.config.allow_reload_in_prod:
                self.logger.warning("Allowing app reloads in production mode due to config")
            self.bus.on(topic=HASSETTE_EVENT_FILE_WATCHER, handler=self.handle_change_event)
        else:
            self.logger.warning("Not watching for app changes, dev_mode is disabled")

    def _setup_dependency_listeners(self) -> None:
        self._dependency_ready = {}

        websocket_service = getattr(self.hassette, "_websocket_service", None)
        if websocket_service is None:
            self._dependency_ready["websocket"] = True
        else:
            self._dependency_ready["websocket"] = self._is_resource_ready(websocket_service)
            self.bus.on(
                topic=HASSETTE_EVENT_WEBSOCKET_STATUS,
                handler=self._on_websocket_connected,
                where=lambda event: getattr(event.payload, "event_type", None) == "connected",
                once=True,
            )

        api_service = getattr(self.hassette, "_api_service", None)
        if api_service is None:
            self._dependency_ready["api"] = True
            self._api_unique_name = None
        else:
            self._api_unique_name = getattr(api_service, "unique_name", None)
            self._dependency_ready["api"] = self._is_resource_ready(api_service)

            if self._api_unique_name:
                self.bus.on(
                    topic=HASSETTE_EVENT_SERVICE_STATUS,
                    handler=self._on_api_service_status,
                    where=lambda event: (
                        getattr(getattr(event.payload, "data", None), "resource_name", None) == self._api_unique_name
                        and getattr(getattr(event.payload, "data", None), "status", None) == ResourceStatus.RUNNING
                    ),
                    once=True,
                )

    def _check_initial_boot_conditions(self) -> None:
        if self._initialization_scheduled:
            return

        if self.shutdown_event.is_set():
            self.logger.debug("Shutdown requested before app initialization, skipping boot")
            return

        if not self._dependency_ready:
            # No dependencies to track; start immediately.
            self.logger.debug("No dependencies tracked, scheduling app initialization")
            self._initialization_scheduled = True
            self.task_bucket.spawn(self.initialize_apps(), name="app-handler:initialize-apps")
            return

        pending = [name for name, ready in self._dependency_ready.items() if not ready]
        if pending:
            self.logger.debug("Waiting for dependencies before booting apps: %s", ", ".join(pending))
            return

        self.logger.debug("All dependencies ready, scheduling app initialization")
        self._initialization_scheduled = True
        self.task_bucket.spawn(self.initialize_apps(), name="app-handler:initialize-apps")

    def _is_resource_ready(self, resource: "Resource | None") -> bool:
        if resource is None:
            return True

        ready_event = getattr(resource, "ready_event", None)
        if isinstance(ready_event, asyncio.Event) and ready_event.is_set():
            return True

        is_ready = getattr(resource, "is_ready", None)
        if callable(is_ready):
            try:
                if is_ready():
                    return True
            except Exception:
                self.logger.debug("Error while checking readiness for %s", resource, exc_info=True)

        status = getattr(resource, "status", None)
        if status == ResourceStatus.RUNNING:
            return True

        return False

    async def _on_websocket_connected(self, event: "Event[Any]") -> None:  # pragma: no cover - signature for bus
        self.logger.debug("Received websocket connected event, marking dependency ready")
        self._dependency_ready["websocket"] = True
        self._check_initial_boot_conditions()

    async def _on_api_service_status(self, event: "Event[Any]") -> None:  # pragma: no cover - signature for bus
        if not self._api_unique_name:
            return

        payload = getattr(event, "payload", None)
        data = getattr(payload, "data", None)
        if not data or getattr(data, "resource_name", None) != self._api_unique_name:
            return

        if getattr(data, "status", None) != ResourceStatus.RUNNING:
            return

        self.logger.debug("API service reported ready, marking dependency satisfied")
        self._dependency_ready["api"] = True
        self._check_initial_boot_conditions()

    async def on_shutdown(self) -> None:
        """Shutdown all app instances gracefully."""
        self.logger.debug("Stopping '%s' %s", self.class_name, self.role)
        self.mark_not_ready(reason="shutting-down")

        self.bus.remove_all_listeners()

        # Flatten and iterate
        for instances in list(self.apps.values()):
            for inst in list(instances.values()):
                try:
                    with anyio.fail_after(self.hassette.config.app_shutdown_timeout_seconds):
                        await inst.shutdown()

                        # in case the app does not call its own cleanup
                        # which is honestly a better user experience
                        await inst.cleanup()
                    self.logger.debug("App %s shutdown successfully", inst.app_config.instance_name)
                except Exception:
                    self.logger.exception("Failed to shutdown app %s", inst.app_config.instance_name)

        self.apps.clear()
        self.failed_apps.clear()

    def get(self, app_key: str, index: int = 0) -> "App[AppConfig] | None":
        """Get a specific app instance if running."""
        return self.apps.get(app_key, {}).get(index)

    def all(self) -> list["App[AppConfig]"]:
        """All running app instances."""
        return [inst for group in self.apps.values() for inst in group.values()]

    async def initialize_apps(self) -> None:
        """Initialize all configured and enabled apps, called at AppHandler startup."""

        if not self.apps_config:
            self.logger.debug("No apps configured, skipping initialization")
            return

        if not await self.hassette.wait_for_ready(
            [
                self.hassette._websocket_service,
                self.hassette._api_service,
                self.hassette._bus_service,
                self.hassette._scheduler_service,
            ]
        ):
            self.logger.warning("Dependencies never became ready; skipping app startup")
            return

        try:
            tasks = await self._initialize_apps()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    self.logger.exception("Error during app initialization: %s", result)
            if not self.apps:
                self.logger.warning("No apps were initialized successfully")
            else:
                self.logger.info("Initialized %d apps", sum(len(v) for v in self.apps.values()))

            await self.hassette.send_event(
                HASSETTE_EVENT_APP_LOAD_COMPLETED,
                HassetteEmptyPayload.create_event(topic=HASSETTE_EVENT_APP_LOAD_COMPLETED),
            )
        except Exception as e:
            self.logger.exception("Failed to initialize apps")
            await self.handle_crash(e)
            raise

    async def _set_only_app(self):
        """Determine if any app is marked as only, and set self.only_app accordingly."""

        if not self.hassette.config.dev_mode:
            if not self.hassette.config.allow_only_app_in_prod:
                self.logger.warning("Disallowing use of `only_app` decorator in production mode")
                self.only_app = None
                return
            self.logger.warning("Allowing use of `only_app` decorator in production mode due to config")

        only_apps: list[str] = []
        for app_manifest in self.active_apps_config.values():
            try:
                app_class = load_app_class(app_manifest)
                if app_class._only_app:
                    only_apps.append(app_manifest.app_key)
            except (UndefinedUserConfigError, InvalidInheritanceError):
                self.logger.error(
                    "Failed to load app %s due to bad configuration - check previous logs for details",
                    app_manifest.display_name,
                )
            except Exception:
                self.logger.exception("Failed to load app class for %s", app_manifest.display_name)

        if not only_apps:
            self.only_app = None
            return

        if len(only_apps) > 1:
            keys = ", ".join(app for app in only_apps)
            raise RuntimeError(f"Multiple apps marked as only: {keys}")

        self.only_app = only_apps[0]
        self.logger.warning("App %s is marked as only, skipping all others", self.only_app)

    async def _initialize_apps(self, apps: set[str] | None = None) -> list[asyncio.Task]:
        """Initialize all or a subset of apps by key. If apps is None, initialize all enabled apps."""

        tasks: list[asyncio.Task] = []
        await self._set_only_app()

        apps = apps if apps is not None else set(self.active_apps_config.keys())

        for app_key in apps:
            app_manifest = self.active_apps_config.get(app_key)
            if not app_manifest:
                self.logger.debug("Skipping disabled or unknown app %s", app_key)
                continue
            try:
                self._create_app_instances(app_key, app_manifest)
            except (UndefinedUserConfigError, InvalidInheritanceError):
                self.logger.error(
                    "Failed to load app %s due to bad configuration - check previous logs for details", app_key
                )
                continue
            except Exception:
                self.logger.exception("Failed to load app class for %s", app_key)
                continue

            tasks.append(self.task_bucket.spawn(self._initialize_app_instances(app_key, app_manifest)))

        return tasks

    def _create_app_instances(
        self,
        app_key: str,
        app_manifest: "AppManifest",
        force_reload: bool = False,
        indices: set[int] | None = None,
    ) -> None:
        """Create app instances from a manifest, validating config.

        Args:
            app_key (str): The key of the app, as found in hassette.toml.
            app_manifest (AppManifest): The manifest containing configuration.
            force_reload (bool): Whether to force reloading the underlying module.
            indices (set[int] | None): Specific instance indices to (re)create. If None, all instances are created.
        """
        try:
            app_class = load_app_class(app_manifest, force_reload=force_reload)
        except Exception as e:
            self.logger.exception("Failed to load app class for %s", app_key)
            self.failed_apps[app_key].append((0, e))
            return

        class_name = app_class.__name__
        app_class.app_manifest = app_manifest
        app_configs = app_manifest.app_config

        # toml data can be a dict or a list of dicts, but AppManifest should handle conversion for us
        if not isinstance(app_configs, list):
            raise ValueError(f"App {app_key} config is not a list, found {type(app_configs)}")

        target_indices = indices if indices is None else set(indices)

        for idx, config in enumerate(app_configs):
            if target_indices is not None and idx not in target_indices:
                continue
            if isinstance(config, dict):
                config_data = dict(config)
            elif hasattr(config, "model_dump"):
                config_data = typing.cast("dict[str, Any]", config.model_dump())
            else:
                config_data = dict(config)

            instance_name = config_data.get("instance_name")
            if not instance_name:
                raise ValueError(f"App {app_key} instance {idx} is missing instance_name")
            try:
                validated = app_class.app_config_cls.model_validate(config_data)
                app_instance = app_class.create(hassette=self.hassette, app_config=validated, index=idx)
                self.apps[app_key][idx] = app_instance
            except Exception as e:
                self.logger.exception("Failed to validate/init config for %s (%s)", instance_name, class_name)
                self.failed_apps[app_key].append((idx, e))
                continue

    async def _initialize_app_instances(
        self, app_key: str, app_manifest: "AppManifest", indices: set[int] | None = None
    ) -> None:
        """Initialize all instances of a given app_key.

        Args:
            app_key (str): The key of the app, as found in hassette.toml.
          app_manifest (AppManifest): The manifest containing configuration.
        """

        class_name = app_manifest.class_name
        instances = self.apps.get(app_key, {})
        if indices is None:
            target_items = instances.items()
        else:
            target_items = ((idx, instances[idx]) for idx in sorted(indices) if idx in instances)

        for idx, inst in target_items:
            try:
                with anyio.fail_after(self.hassette.config.app_startup_timeout_seconds):
                    await inst.initialize()
                    inst.mark_ready(reason="initialized")
                self.logger.debug("App '%s' (%s) initialized successfully", inst.app_config.instance_name, class_name)
            except TimeoutError as e:
                self.logger.exception(
                    "Timed out while starting app '%s' (%s)", inst.app_config.instance_name, class_name
                )
                inst.status = ResourceStatus.STOPPED
                self.failed_apps[app_key].append((idx, e))
            except Exception as e:
                self.logger.exception("Failed to start app '%s' (%s)", inst.app_config.instance_name, class_name)
                inst.status = ResourceStatus.STOPPED
                self.failed_apps[app_key].append((idx, e))

    async def handle_change_event(self, event: "HassetteFileWatcherEvent") -> None:
        """Handle changes detected by the watcher."""
        await self.handle_changes(event.payload.data.changed_file_path)

    async def refresh_config(self) -> tuple[dict[str, "AppManifest"], dict[str, "AppManifest"]]:
        """Reload the configuration and return (original_apps_config, current_apps_config)."""
        original_apps_config = deepcopy(self.active_apps_config)

        # Reinitialize config to pick up changes.
        # https://docs.pydantic.dev/latest/concepts/pydantic_settings/#in-place-reloading
        try:
            self.hassette.config.__init__()
        except Exception as e:
            self.logger.exception("Failed to reload configuration: %s", e)

        self.set_apps_configs(self.hassette.config.apps)
        curr_apps_config = deepcopy(self.active_apps_config)

        return original_apps_config, curr_apps_config

    async def handle_changes(self, changed_file_path: Path | None = None) -> None:
        """Handle changes detected by the watcher."""

        original_apps_config, curr_apps_config = await self.refresh_config()

        # recalculate only_app in case it changed
        await self._set_only_app()

        changes = self._calculate_app_changes(original_apps_config, curr_apps_config, changed_file_path)
        self.logger.debug(
            (
                "App changes detected - orphans: %s, removed_instances: %s, new: %s, new_instances: %s, "
                "reimport: %s, reload: %s, reload_instances: %s"
            ),
            changes.removed_apps,
            changes.removed_instances,
            changes.new_apps,
            changes.new_instances,
            changes.reimport_apps,
            changes.reload_apps,
            changes.reload_instances,
        )
        await self._handle_removed_apps(changes.removed_apps, changes.removed_instances)
        await self._handle_new_apps(changes.new_apps, changes.new_instances)
        await self._reload_apps_due_to_file_change(changes.reimport_apps)
        await self._reload_apps_due_to_config(changes.reload_apps, changes.reload_instances)

        await self.hassette.send_event(
            HASSETTE_EVENT_APP_LOAD_COMPLETED,
            HassetteEmptyPayload.create_event(topic=HASSETTE_EVENT_APP_LOAD_COMPLETED),
        )

    def _calculate_app_changes(
        self,
        original_apps_config: dict[str, "AppManifest"],
        curr_apps_config: dict[str, "AppManifest"],
        changed_path: Path | None,
    ) -> AppChangeSet:
        """Return the set of app and instance changes detected between two configurations."""

        changes = AppChangeSet()

        original_app_keys = set(original_apps_config.keys())
        curr_app_keys = set(curr_apps_config.keys())
        if self.only_app:
            curr_app_keys = {k for k in curr_app_keys if k == self.only_app}

        changes.removed_apps = original_app_keys - curr_app_keys
        changes.new_apps = curr_app_keys - original_app_keys

        changes.reimport_apps = {
            app.app_key
            for app in curr_apps_config.values()
            if (changed_path is not None and app.get_full_path() == changed_path)
        }

        shared_keys = (original_app_keys & curr_app_keys) - changes.reimport_apps

        for app_key in shared_keys:
            original_manifest = original_apps_config[app_key]
            current_manifest = curr_apps_config[app_key]

            if self._manifest_metadata_changed(original_manifest, current_manifest):
                changes.reload_apps.add(app_key)

            original_configs = self._normalize_manifest_configs(original_manifest)
            current_configs = self._normalize_manifest_configs(current_manifest)

            original_len = len(original_configs)
            current_len = len(current_configs)

            if current_len > original_len:
                new_indices = set(range(original_len, current_len))
                if new_indices:
                    changes.new_instances[app_key] = new_indices

            if original_len > current_len:
                removed_indices = set(range(current_len, original_len))
                if removed_indices:
                    changes.removed_instances[app_key] = removed_indices

            overlap = min(original_len, current_len)
            changed_indices = {
                idx
                for idx in range(overlap)
                if original_configs[idx] != current_configs[idx]
            }
            if changed_indices:
                changes.reload_instances[app_key] = changed_indices

        return changes

    def _manifest_metadata_changed(
        self, original_manifest: "AppManifest", current_manifest: "AppManifest"
    ) -> bool:
        original_meta = original_manifest.model_dump()
        current_meta = current_manifest.model_dump()
        original_meta.pop("app_config", None)
        current_meta.pop("app_config", None)
        return original_meta != current_meta

    def _normalize_manifest_configs(self, manifest: "AppManifest") -> list[dict[str, Any]]:
        configs = manifest.app_config or []
        normalized: list[dict[str, Any]] = []
        for item in configs:
            if hasattr(item, "model_dump"):
                normalized.append(typing.cast("dict[str, Any]", item.model_dump()))
            elif isinstance(item, dict):
                normalized.append(dict(item))
            else:
                try:
                    normalized.append(dict(item))
                except TypeError:
                    normalized.append({})
        return normalized

    async def _handle_removed_apps(self, orphans: set[str], removed_instances: dict[str, set[int]]) -> None:
        if orphans:
            self.logger.debug("Stopping %d orphaned apps: %s", len(orphans), orphans)
            for app_key in orphans:
                self.logger.debug("Stopping orphaned app %s", app_key)
                try:
                    await self.stop_app(app_key)
                except Exception:
                    self.logger.exception("Failed to stop orphaned app %s", app_key)

        if removed_instances:
            for app_key, indices in removed_instances.items():
                if not indices:
                    continue
                self.logger.debug(
                    "Stopping %d orphaned instances of %s: %s", len(indices), app_key, sorted(indices)
                )
                try:
                    await self.stop_app_instances(app_key, indices)
                except Exception:
                    self.logger.exception(
                        "Failed to stop orphaned instances %s for app %s", sorted(indices), app_key
                    )

    async def _reload_apps_due_to_file_change(self, apps: set[str]) -> None:
        if not apps:
            return

        self.logger.debug("Apps to reimport due to file change: %s", apps)
        for app_key in apps:
            await self.reload_app(app_key, force_reload=True)

    async def _reload_apps_due_to_config(self, apps: set[str], instance_indices: dict[str, set[int]]) -> None:
        if apps:
            self.logger.debug("Apps to reload due to config changes: %s", apps)
            for app_key in apps:
                await self.reload_app(app_key)

        for app_key, indices in instance_indices.items():
            if not indices or app_key in apps:
                continue
            self.logger.debug(
                "Reloading %d instances of %s due to config changes: %s", len(indices), app_key, sorted(indices)
            )
            await self.reload_app_instances(app_key, indices)

    async def stop_app(self, app_key: str) -> None:
        """Stop and remove all instances for a given app_name."""
        instances = self.apps.get(app_key)
        if not instances:
            self.logger.warning("Cannot stop app %s, not found", app_key)
            return
        indices = set(instances.keys())
        self.logger.debug("Stopping %d instances of %s", len(indices), app_key)
        await self.stop_app_instances(app_key, indices)

    async def stop_app_instances(self, app_key: str, indices: set[int]) -> None:
        if not indices:
            return

        instances = self.apps.get(app_key)
        if not instances:
            self.logger.warning("Cannot stop instances %s for app %s, not found", sorted(indices), app_key)
            return

        for idx in sorted(indices):
            inst = instances.pop(idx, None)
            if inst is None:
                self.logger.debug("Instance %s for app %s not running", idx, app_key)
                continue

            try:
                start_time = timer()
                with anyio.fail_after(self.hassette.config.app_shutdown_timeout_seconds):
                    await inst.shutdown()

                end_time = timer()
                friendly_time = precisedelta(end_time - start_time, minimum_unit="milliseconds")
                self.logger.debug(
                    "Stopped app '%s' (index %s) in %s",
                    inst.app_config.instance_name,
                    idx,
                    friendly_time,
                )

            except Exception:
                self.logger.exception(
                    "Failed to stop app '%s' (index %s) after %s seconds",
                    inst.app_config.instance_name,
                    idx,
                    self.hassette.config.app_shutdown_timeout_seconds,
                )

        if app_key in self.apps and not self.apps[app_key]:
            self.apps.pop(app_key, None)

        if app_key in self.failed_apps:
            remaining_failures = [
                (idx, exc) for idx, exc in self.failed_apps[app_key] if idx not in indices
            ]
            if remaining_failures:
                self.failed_apps[app_key] = remaining_failures
            else:
                self.failed_apps.pop(app_key, None)

    async def _handle_new_apps(self, apps: set[str], new_instances: dict[str, set[int]]) -> None:
        """Start new apps or additional instances that were added to the configuration."""

        if apps:
            self.logger.debug("Starting %d new apps: %s", len(apps), list(apps))
            try:
                await self._initialize_apps(apps)
            except Exception:
                self.logger.exception("Failed to start new apps")

        for app_key, indices in new_instances.items():
            if not indices or app_key in apps:
                continue

            manifest = self.active_apps_config.get(app_key)
            if not manifest:
                self.logger.debug("Skipping new instances for disabled or missing app %s", app_key)
                continue

            self.logger.debug(
                "Starting %d new instances for %s: %s", len(indices), app_key, sorted(indices)
            )
            try:
                self._create_app_instances(app_key, manifest, indices=indices)
                await self._initialize_app_instances(app_key, manifest, indices=indices)
            except Exception:
                self.logger.exception("Failed to start new instances for app %s", app_key)

    async def reload_app(self, app_key: str, force_reload: bool = False) -> None:
        """Stop and reinitialize a single app by key (based on current config)."""
        self.logger.debug("Reloading app %s", app_key)
        try:
            await self.stop_app(app_key)
            # Initialize only that app from the current config if present and enabled
            manifest = self.active_apps_config.get(app_key)
            if not manifest:
                if manifest := self.apps_config.get(app_key):
                    self.logger.warning("Cannot reload app %s, not enabled", app_key)
                    return
                self.logger.warning("Cannot reload app %s, not found", app_key)
                return

            assert manifest is not None, "Manifest should not be None"

            self._create_app_instances(app_key, manifest, force_reload=force_reload)
            await self._initialize_app_instances(app_key, manifest)
        except Exception:
            self.logger.exception("Failed to reload app %s", app_key)

    async def reload_app_instances(
        self, app_key: str, indices: set[int], force_reload: bool = False
    ) -> None:
        if not indices:
            return

        manifest = self.active_apps_config.get(app_key)
        if not manifest:
            if app_key in self.apps_config:
                self.logger.warning("Cannot reload instances for app %s, app is not enabled", app_key)
            else:
                self.logger.warning("Cannot reload instances for app %s, not found in config", app_key)
            return

        await self.stop_app_instances(app_key, indices)
        self._create_app_instances(app_key, manifest, force_reload=force_reload, indices=indices)
        await self._initialize_app_instances(app_key, manifest, indices=indices)
