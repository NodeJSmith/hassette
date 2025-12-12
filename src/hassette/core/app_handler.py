import asyncio
import typing
from collections import defaultdict
from copy import deepcopy
from logging import getLogger
from pathlib import Path
from timeit import default_timer as timer

import anyio
from deepdiff import DeepDiff
from humanize import precisedelta

import hassette.event_handling.accessors as A
from hassette.app.app import App
from hassette.bus import Bus
from hassette.events.hassette import HassetteSimpleEvent
from hassette.exceptions import InvalidInheritanceError, UndefinedUserConfigError
from hassette.resources.base import Resource
from hassette.types import Topic
from hassette.types.enums import ResourceStatus
from hassette.utils.app_utils import (
    class_already_loaded,
    class_failed_to_load,
    get_class_load_error,
    get_loaded_class,
    load_app_class_from_manifest,
)
from hassette.utils.exception_utils import get_short_traceback

if typing.TYPE_CHECKING:
    from hassette import AppConfig, Hassette
    from hassette.config.classes import AppManifest

LOGGER = getLogger(__name__)
LOADED_CLASSES: "dict[tuple[str, str], type[App[AppConfig]]]" = {}
ROOT_PATH = "root"
USER_CONFIG_PATH = "user_config"


class AppHandler(Resource):
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
        inst.set_apps_configs(hassette.config.app_manifests)
        inst.only_app = None
        inst.apps = defaultdict(dict)
        inst.failed_apps = defaultdict(list)
        inst.bus = inst.add_child(Bus)
        return inst

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
        if self.hassette.config.dev_mode or self.hassette.config.allow_reload_in_prod:
            if self.hassette.config.allow_reload_in_prod:
                self.logger.warning("Allowing app reloads in production mode due to config")
            self.bus.on(topic=Topic.HASSETTE_EVENT_FILE_WATCHER, handler=self.handle_change_event)
        else:
            self.logger.warning("Not watching for app changes, dev_mode is disabled")

        await self.hassette.wait_for_ready(self.hassette._websocket_service)
        self.mark_ready("initialized")

    async def after_initialize(self) -> None:
        self.logger.debug("Scheduling app initialization")
        self.task_bucket.spawn(self.initialize_apps())

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
                    self.logger.error(
                        "Failed to shutdown app %s:\n%s", inst.app_config.instance_name, get_short_traceback()
                    )

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
                self.hassette._state_proxy,
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
                success_count = sum(len(v) for v in self.apps.values())
                fail_count = sum(len(v) for v in self.failed_apps.values())
                self.logger.info("Initialized %d apps successfully, %d failed to start", success_count, fail_count)

            await self.hassette.send_event(
                Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED,
                HassetteSimpleEvent.create_event(topic=Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED),
            )
        except Exception as e:
            self.logger.exception("Failed to initialize apps")
            await self.handle_crash(e)
            raise

    async def _set_only_app(self):
        """Determine if any app is marked as only, and set self.only_app accordingly."""

        only_apps: list[str] = []
        for app_manifest in self.active_apps_config.values():
            try:
                if class_failed_to_load(app_manifest.full_path, app_manifest.class_name):
                    self.logger.debug(
                        "Skipping only_app check for '%s' because class failed to load", app_manifest.app_key
                    )
                    continue
                if class_already_loaded(app_manifest.full_path, app_manifest.class_name):
                    app_class = get_loaded_class(app_manifest.full_path, app_manifest.class_name)
                else:
                    app_class = load_app_class_from_manifest(app_manifest)
                if app_class._only_app:
                    only_apps.append(app_manifest.app_key)
            except (UndefinedUserConfigError, InvalidInheritanceError):
                self.logger.error(
                    "Failed to load app '%s' due to bad configuration - check previous logs for details",
                    app_manifest.display_name,
                )
            except Exception:
                self.logger.error(
                    "Failed to load app class for '%s':\n%s", app_manifest.display_name, get_short_traceback()
                )

        if not only_apps:
            self.only_app = None
            return

        if not self.hassette.config.dev_mode:
            if not self.hassette.config.allow_only_app_in_prod:
                self.logger.warning("Disallowing use of `only_app` decorator in production mode")
                self.only_app = None
                return
            self.logger.warning("Allowing use of `only_app` decorator in production mode due to config")

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
                    "Failed to load app '%s' due to bad configuration - check previous logs for details", app_key
                )
                continue
            except Exception:
                self.logger.error("Failed to load app class for '%s':\n%s", app_key, get_short_traceback())
                continue

            tasks.append(self.task_bucket.spawn(self._initialize_app_instances(app_key, app_manifest)))

        return tasks

    def _create_app_instances(self, app_key: str, app_manifest: "AppManifest", force_reload: bool = False) -> None:
        """Create app instances from a manifest, validating config.

        Args:
            app_key: The key of the app, as found in hassette.toml.
            app_manifest: The manifest containing configuration.
        """

        already_loaded = class_already_loaded(app_manifest.full_path, app_manifest.class_name)
        already_failed = class_failed_to_load(app_manifest.full_path, app_manifest.class_name)

        # if we are forcing a reload we have to try again
        # or if we've never loaded it before/failed to load it before, we have to try to load it
        if force_reload or (not already_loaded and not already_failed):
            try:
                app_class = load_app_class_from_manifest(app_manifest, force_reload=force_reload)
            except Exception as e:
                self.logger.error("Failed to load app class for '%s':\n%s", app_key, get_short_traceback())
                self.failed_apps[app_key].append((0, e))
                return
        # if we've already failed to load it (and we're not forcing a reload), we can't load it again
        elif already_failed:
            self.logger.debug("Cannot create app instances for '%s' because class failed to load previously", app_key)
            load_error = get_class_load_error(app_manifest.full_path, app_manifest.class_name)
            self.failed_apps[app_key].append((0, load_error))
            return
        # else, just get the already loaded class
        elif already_loaded:
            app_class = get_loaded_class(app_manifest.full_path, app_manifest.class_name)

        class_name = app_class.__name__
        app_class.app_manifest = app_manifest
        app_configs = app_manifest.app_config

        # toml data can be a dict or a list of dicts
        # AppManifest should handle conversion for us but we're being cautious here
        app_configs = [app_configs] if not isinstance(app_configs, list) else app_configs

        for idx, config in enumerate(app_configs):
            instance_name = config.get("instance_name")
            if not instance_name:
                raise ValueError(f"App {app_key} instance {idx} is missing instance_name")
            try:
                validated = app_class.app_config_cls.model_validate(config)
                app_instance = app_class.create(hassette=self.hassette, app_config=validated, index=idx)
                self.apps[app_key][idx] = app_instance
            except Exception as e:
                self.logger.error(
                    "Failed to validate/init config for %s (%s):\n%s",
                    instance_name,
                    class_name,
                    get_short_traceback(),
                )
                self.failed_apps[app_key].append((idx, e))
                continue

    async def _initialize_app_instances(self, app_key: str, app_manifest: "AppManifest") -> None:
        """Initialize all instances of a given app_key.

        Args:
            app_key: The key of the app, as found in hassette.toml.
            app_manifest (AppManifest): The manifest containing configuration.

        """

        class_name = app_manifest.class_name
        for idx, inst in self.apps.get(app_key, {}).items():
            try:
                with anyio.fail_after(self.hassette.config.app_startup_timeout_seconds):
                    await inst.initialize()
                    inst.mark_ready(reason="initialized")
                self.logger.debug("App '%s' (%s) initialized successfully", inst.app_config.instance_name, class_name)
            except TimeoutError as e:
                self.logger.error(
                    "Timed out while starting app '%s' (%s):\n%s",
                    inst.app_config.instance_name,
                    class_name,
                    get_short_traceback(5),
                )
                inst.status = ResourceStatus.STOPPED
                self.failed_apps[app_key].append((idx, e))
            except Exception as e:
                self.logger.error(
                    "Failed to start app '%s' (%s):\n%s",
                    inst.app_config.instance_name,
                    class_name,
                    get_short_traceback(5),
                )
                inst.status = ResourceStatus.STOPPED
                self.failed_apps[app_key].append((idx, e))

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

        original_apps_config, curr_apps_config = await self.refresh_config()

        # recalculate only_app in case it changed
        await self._set_only_app()

        orphans, new_apps, reimport_apps, reload_apps = self._calculate_app_changes(
            original_apps_config, curr_apps_config, changed_file_path
        )
        self.logger.info(
            "App changes detected - orphans: %s, new: %s, reimport: %s, reload: %s",
            orphans,
            new_apps,
            reimport_apps,
            reload_apps,
        )
        await self._handle_removed_apps(orphans)
        await self._handle_new_apps(new_apps)
        await self._reload_apps_due_to_file_change(reimport_apps)
        await self._reload_apps_due_to_config(reload_apps)

        await self.hassette.send_event(
            Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED,
            HassetteSimpleEvent.create_event(topic=Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED),
        )

    def _calculate_app_changes(
        self,
        original_apps_config: dict[str, "AppManifest"],
        curr_apps_config: dict[str, "AppManifest"],
        changed_path: Path | None,
    ) -> tuple[set[str], set[str], set[str], set[str]]:
        """Return 4 sets of app keys: (orphans, new_apps, reimport_apps, reload_apps).

        Args:
            original_apps_config: The original apps configuration.
            curr_apps_config: The current apps configuration.
            changed_path: The path of the file that changed, if any.

        Returns:
            A tuple containing four sets:
                - orphans: Apps that were removed from the configuration.
                - new_apps: Apps that were added to the configuration.
                - reimport_apps: Apps that need to be reimported due to file changes.
                - reload_apps: Apps that need to be reloaded due to configuration changes.
        """

        config_diff = DeepDiff(
            original_apps_config, curr_apps_config, ignore_order=True, include_paths=[ROOT_PATH, USER_CONFIG_PATH]
        )

        original_app_keys = set(original_apps_config.keys())
        curr_app_keys = set(curr_apps_config.keys())
        if self.only_app:
            curr_app_keys = {k for k in curr_app_keys if k == self.only_app}

        orphans = original_app_keys - curr_app_keys
        new_apps = curr_app_keys - original_app_keys

        reimport_apps = {app.app_key for app in curr_apps_config.values() if app.full_path == changed_path}

        reload_apps = {
            app_key
            for app_key in config_diff.affected_root_keys
            if app_key not in new_apps and app_key not in orphans and app_key not in reimport_apps
        }

        return orphans, new_apps, reimport_apps, reload_apps

    async def _handle_removed_apps(self, orphans: set[str]) -> None:
        if not orphans:
            return

        self.logger.debug("Apps removed from config: %s", orphans)

        self.logger.debug("Stopping %d orphaned apps: %s", len(orphans), orphans)
        for app_key in orphans:
            self.logger.debug("Stopping orphaned app %s", app_key)
            try:
                await self.stop_app(app_key)
            except Exception:
                self.logger.error("Failed to stop orphaned app %s:\n%s", app_key, get_short_traceback())

    async def _reload_apps_due_to_file_change(self, apps: set[str]) -> None:
        if not apps:
            return

        self.logger.debug("Apps to reimport due to file change: %s", apps)
        for app_key in apps:
            await self.reload_app(app_key, force_reload=True)

    async def _reload_apps_due_to_config(self, apps: set[str]) -> None:
        if not apps:
            return

        self.logger.debug("Apps to reload due to config changes: %s", apps)
        for app_key in apps:
            await self.reload_app(app_key)

    async def stop_app(self, app_key: str) -> None:
        """Stop and remove all instances for a given app_name."""
        instances = self.apps.pop(app_key, None)
        if not instances:
            self.logger.warning("Cannot stop app %s, not found", app_key)
            return
        self.logger.debug("Stopping %d instances of %s", len(instances), app_key)

        for inst in instances.values():
            try:
                start_time = timer()
                with anyio.fail_after(self.hassette.config.app_shutdown_timeout_seconds):
                    await inst.shutdown()

                end_time = timer()
                friendly_time = precisedelta(end_time - start_time, minimum_unit="milliseconds")
                self.logger.debug("Stopped app '%s' in %s", inst.app_config.instance_name, friendly_time)

            except Exception:
                self.logger.error(
                    "Failed to stop app '%s' after %s seconds:\n%s",
                    inst.app_config.instance_name,
                    self.hassette.config.app_shutdown_timeout_seconds,
                    get_short_traceback(),
                )

    async def _handle_new_apps(self, apps: set[str]) -> None:
        """Start any apps that are in config but not currently running."""
        if not apps:
            return

        self.logger.debug("Starting %d new apps: %s", len(apps), list(apps))
        await self._initialize_apps(apps)

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
            self.logger.error("Failed to reload app %s:\n%s", app_key, get_short_traceback())
