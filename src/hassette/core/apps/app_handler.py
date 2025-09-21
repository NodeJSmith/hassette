import asyncio
import importlib.machinery
import importlib.util
import sys
import typing
from collections import defaultdict
from copy import deepcopy
from logging import getLogger
from pathlib import Path

import anyio
from deepdiff import DeepDiff
from watchfiles import awatch

from hassette import Service
from hassette.config.core_config import HassetteConfig
from hassette.core.apps.app import App, AppSync
from hassette.core.classes import Resource
from hassette.core.enums import ResourceStatus
from hassette.exceptions import InvalidInheritanceError, UndefinedUserConfigError

if typing.TYPE_CHECKING:
    from hassette.config.app_manifest import AppManifest
    from hassette.core.apps.app_config import AppConfig
    from hassette.core.core import Hassette

LOGGER = getLogger(__name__)
FAIL_AFTER_SECONDS = 10
LOADED_CLASSES: "dict[tuple[str, str], type[App[AppConfig]]]" = {}

CHECK_COUNT = 0


def _manifest_key(app_name: str, index: int) -> str:
    # Human-friendly identifier for logs; not used as dict key.
    return f"{app_name}[{index}]"


class _AppWatcher(Service):
    """Background task to watch for file changes and reload apps."""

    # TODO: should this be separated from app_handler? i don't like how tightly coupled they are
    # TODO: use events to signal changes instead of direct method calls? (almost definitely - question is now or later?)
    # TODO: double check only_app when any source files change, in case the only flag changed

    def __init__(self, hassette: "Hassette", app_handler: "_AppHandler", *args, **kwargs) -> None:
        super().__init__(hassette, *args, **kwargs)
        self.app_handler = app_handler

        self.set_logger_to_debug()

    async def run_forever(self) -> None:
        """Watch app directories for changes and trigger reloads."""
        global CHECK_COUNT
        try:
            self.logger.info("Starting app watcher service")

            # TODO: abstract this wait-for-running logic or dependencies list/lifecycle method
            # i've written this in enough places now that i need to stop thinking i don't know how
            # to make this a utility function
            while self.app_handler.status != ResourceStatus.RUNNING:
                if self.hassette._shutdown_event.is_set():
                    self.logger.warning("Shutdown in progress, aborting app watcher")
                    return
                await asyncio.sleep(0.1)

            paths = self.hassette.config.get_watchable_files()

            self.logger.info("Watching app directories for changes: %s", ", ".join(str(p) for p in paths))

            await self.handle_start()
            async for changes in awatch(*paths, stop_event=self.hassette._shutdown_event):
                CHECK_COUNT += 1
                self.logger.info("Watcher iteration %d: detected changes: %s", CHECK_COUNT, changes)

                if self.hassette._shutdown_event.is_set():
                    break

                for _, changed_path in changes:
                    changed_path = Path(changed_path).resolve()
                    self.logger.info("Detected change in %s", changed_path)
                    await self.handle_changes(changed_path)
                    continue
        except Exception as e:
            self.logger.exception("App watcher encountered an error, exception args: %s", e.args)
            await self.handle_crash(e)
            raise

    async def handle_changes(self, changed_path: Path) -> None:
        """Handle changes detected by the watcher."""

        # TODO: clean this up - separate it into smaller methods, etc.

        original_apps_config = deepcopy(self.app_handler.apps_config)

        # reinitialize config to pick up changes
        self.hassette.config.__init__()
        self.app_handler.set_apps_configs(self.hassette.config.apps)
        curr_apps_config = deepcopy(self.app_handler.apps_config)

        diff = DeepDiff(original_apps_config, curr_apps_config, ignore_order=True)
        config_diff = DeepDiff(
            original_apps_config, curr_apps_config, ignore_order=True, include_paths=["root", "user_config"]
        )

        if not diff:
            self.logger.debug("No changes in app configuration detected")
        else:
            self.logger.debug("App configuration changes detected: %s", diff)

        original_app_keys = set(original_apps_config.keys())
        curr_app_keys = set(curr_apps_config.keys())

        # handle stopping apps due to config changes
        orphans = original_app_keys - curr_app_keys
        if orphans:
            self.logger.info("Apps removed from config: %s", orphans)
            await self.app_handler.stop_orphans(orphans)

        # handle loading new apps due to config changes
        new_apps = curr_app_keys - original_app_keys
        if not new_apps:
            self.logger.debug("No new apps to add")
        else:
            self.logger.info("New apps added to config: %s", new_apps)
            await self.app_handler.start_new_apps()

        # handle reloading apps due to source code changes
        force_reload_apps = {app.app_key for app in curr_apps_config.values() if app.full_path == changed_path}
        if force_reload_apps:
            self.logger.debug("Apps to force reload due to file change: %s", force_reload_apps)
            for app_key in force_reload_apps.copy():
                if app_key in new_apps or app_key in orphans:
                    continue  # already handled
                self.logger.info("Reloading app %s due to file change", app_key)
                await self.app_handler.reload_app(app_key, force_reload=True)

        # handle reloading apps due to config changes
        if config_diff:
            self.logger.debug("App configuration changes detected: %s", config_diff)
            app_keys = config_diff.affected_root_keys
            for app_key in app_keys:
                if app_key in new_apps or app_key in orphans or app_key in force_reload_apps:
                    continue  # already handled
                self.logger.info("Reloading app %s due to configuration change", app_key)
                await self.app_handler.reload_app(app_key)


class _AppHandler(Resource):
    """Manages the lifecycle of apps in Hassette.

    - Deterministic storage: apps[app_name][index] -> App
    - Tracks per-app failures in failed_apps for observability
    """

    # TODO: handle stopping/starting individual app instances, instead of all apps of a class/key
    # no need to restart app index 2 if only app index 0 changed, etc.

    apps_config: dict[str, "AppManifest"]
    """Copy of Hassette's config apps"""

    def __init__(self, hassette: "Hassette") -> None:
        super().__init__(hassette)
        self.apps_config = {}

        self.set_logger_to_debug()

        self.set_apps_configs(self.hassette.config.apps)

        self.only_app: str | None = None

        self.apps: dict[str, dict[int, App]] = defaultdict(dict)
        """Running apps"""

        self.failed_apps: dict[str, list[tuple[int, Exception]]] = defaultdict(list)
        """Apps we could not start/failed to start"""

    def set_apps_configs(self, apps_config: dict[str, "AppManifest"]) -> None:
        """Set the apps configuration.

        Args:
            apps_config (dict[str, AppManifest]): The new apps configuration.
        """
        self.logger.info("Updating apps configuration")
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

    async def initialize(self) -> None:
        """Start handler and initialize configured apps."""
        await self.initialize_apps()
        await super().initialize()

    async def shutdown(self) -> None:
        """Shutdown all app instances gracefully."""
        self.logger.debug("Stopping '%s' %s", self.class_name, self.role)

        # Flatten and iterate
        for app_key, instances in list(self.apps.items()):
            for index, app_instance in list(instances.items()):
                ident = _manifest_key(app_key, index)
                try:
                    with anyio.fail_after(FAIL_AFTER_SECONDS):
                        await app_instance.shutdown()
                    self.logger.info("App %s shutdown successfully", ident)
                except Exception:
                    self.logger.exception("Failed to shutdown app %s", ident)

        self.apps.clear()
        self.failed_apps.clear()
        await super().shutdown()

    def get(self, app_key: str, index: int = 0) -> App | None:
        """Get a specific app instance if running."""
        return self.apps.get(app_key, {}).get(index)

    def all(self) -> list[App]:
        """All running app instances."""
        return [inst for group in self.apps.values() for inst in group.values()]

    async def stop_app(self, app_key: str) -> None:
        """Stop and remove all instances for a given app_name."""
        instances = self.apps.pop(app_key, None)
        if not instances:
            self.logger.warning("Cannot stop app %s, not found", app_key)
            return
        self.logger.info("Stopping %d instance of %s", len(instances), app_key)
        for index, inst in instances.items():
            ident = _manifest_key(app_key, index)
            try:
                with anyio.fail_after(FAIL_AFTER_SECONDS):
                    await inst.shutdown()
                self.logger.info("Stopped app %s", ident)
            except Exception:
                self.logger.exception("Failed to stop app %s", ident)

    async def stop_orphans(self, app_keys: set[str] | list[str]) -> None:
        """Stop any running apps that are no longer in config."""
        if not app_keys:
            return

        self.logger.info("Stopping %d orphaned apps: %s", len(app_keys), app_keys)
        for app_key in app_keys:
            self.logger.info("Stopping orphaned app %s", app_key)
            await self.stop_app(app_key)

    async def start_new_apps(self) -> None:
        """Start any apps that are in config but not currently running."""
        to_start = {k: v for k, v in self.apps_config.items() if k not in self.apps}
        if not to_start:
            return

        self.logger.info("Starting %d new apps: %s", len(to_start), list(to_start.keys()))
        try:
            await self._initialize_apps()
        except Exception as e:
            self.logger.exception("Failed to start new apps")
            await self.handle_crash(e)
            raise

    async def reload_app(self, app_key: str, force_reload: bool = False) -> None:
        """Stop and reinitialize a single app by key (based on current config)."""
        self.logger.info("Reloading app %s", app_key)

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

    async def initialize_apps(self) -> None:
        with anyio.move_on_after(6) as scope:
            while self.hassette._websocket.status != ResourceStatus.RUNNING and not self.hassette._websocket.connected:
                await asyncio.sleep(0.1)
                if self.hassette._shutdown_event.is_set():
                    self.logger.warning("Shutdown in progress, aborting app initialization")
                    return
                self.logger.info("Waiting for websocket connection...")

        if scope.cancel_called:
            self.logger.warning("App initialization timed out")
            return

        if not self.apps_config:
            self.logger.info("No apps configured, skipping initialization")
            return

        try:
            await self._initialize_apps()
        except Exception as e:
            self.logger.exception("Failed to initialize apps")
            await self.handle_crash(e)
            raise

    async def _set_only_app(self):
        only_apps: list[str] = []
        for app_manifest in self.active_apps_config.values():
            try:
                app_class = load_app_class(app_manifest)
                if app_class._only:
                    only_apps.append(app_class.app_manifest.app_key)
            except (UndefinedUserConfigError, InvalidInheritanceError):
                self.logger.error(
                    "Failed to load app %s due to bad configuration - check previous logs for details",
                    app_manifest.display_name,
                )
            except Exception:
                self.logger.exception("Failed to load app class for %s", app_manifest.display_name)

        if only_apps:
            if len(only_apps) > 1:
                keys = ", ".join(app for app in only_apps)
                raise RuntimeError(f"Multiple apps marked as only: {keys}")
            self.only_app = only_apps[0]
            self.logger.warning("App %s is marked as only, skipping all others", self.only_app)

    async def _initialize_apps(self):
        """Initialize all configured and enabled apps."""

        for app_key, app_manifest in self.active_apps_config.items():
            try:
                self._create_app_instances(app_key, app_manifest)
                await self._initialize_app_instances(app_key, app_manifest)
            except (UndefinedUserConfigError, InvalidInheritanceError):
                self.logger.error(
                    "Failed to load app %s due to bad configuration - check previous logs for details", app_key
                )
                continue
            except Exception:
                self.logger.exception("Failed to load app class for %s", app_key)
                continue

    def _create_app_instances(self, app_key: str, app_manifest: "AppManifest", force_reload: bool = False) -> None:
        """Create app instances from a manifest, validating config.

        Args:
            app_key (str): The key of the app, as found in hassette.toml.
            app_manifest (AppManifest): The manifest containing configuration.
        """

        app_class = load_app_class(app_manifest, force_reload=force_reload)

        class_name = app_class.__name__
        app_class.app_manifest = app_manifest
        app_class.logger = getLogger(f"hassette.{app_class.__name__}")

        # Normalize to list-of-configs; TOML supports both single dict and list of dicts.
        settings_cls = app_class.app_config_cls
        user_configs = app_manifest.user_config
        config_list = user_configs if isinstance(user_configs, list) else [user_configs]

        for idx, config in enumerate(config_list):
            ident = _manifest_key(app_key, idx)
            try:
                validated = settings_cls.model_validate(config)
                app_instance = app_class(self.hassette, app_config=validated, index=idx)
                self.apps[app_key][idx] = app_instance
            except Exception as e:
                self.logger.exception("Failed to validate/init config for %s (%s)", ident, class_name)
                self.failed_apps[app_key].append((idx, e))
                continue

    async def _initialize_app_instances(self, app_key: str, app_manifest: "AppManifest") -> None:
        """Initialize all instances of a given app_key.

        Args:
            app_key (str): The key of the app, as found in hassette.toml.
          app_manifest (AppManifest): The manifest containing configuration.
        """

        class_name = app_manifest.class_name
        for idx, app_instance in self.apps.get(app_key, {}).items():
            ident = _manifest_key(app_key, idx)

            try:
                with anyio.fail_after(FAIL_AFTER_SECONDS):
                    await app_instance.initialize()
                self.logger.info("App %s (%s) initialized successfully", ident, class_name)
            except TimeoutError as e:
                self.logger.exception("Timed out while starting app %s (%s)", ident, class_name)
                app_instance.status = ResourceStatus.STOPPED
                self.failed_apps[app_key].append((idx, e))
            except Exception as e:
                self.logger.exception("Failed to start app %s (%s)", ident, class_name)
                app_instance.status = ResourceStatus.STOPPED
                self.failed_apps[app_key].append((idx, e))


def load_app_class(app_manifest: "AppManifest", force_reload: bool = False) -> "type[App[AppConfig]]":
    """Import the app's class with a canonical package/module identity so isinstance works.

    Args:
        app_manifest (AppManifest): The app manifest containing configuration.

    Returns:
        type[App]: The app class.
    """
    module_path = app_manifest.full_path
    class_name = app_manifest.class_name

    # cache keyed by (absolute file path, class name)
    cache_key = (str(module_path), class_name)

    if force_reload and cache_key in LOADED_CLASSES:
        LOGGER.info("Forcing reload of app class %s from %s", class_name, module_path)
        del LOADED_CLASSES[cache_key]

    if cache_key in LOADED_CLASSES:
        return LOADED_CLASSES[cache_key]

    if not module_path or not class_name:
        raise ValueError(f"App {app_manifest.display_name} is missing filename or class_name")

    pkg_name = HassetteConfig.get_config().app_dir.name
    _ensure_on_sys_path(app_manifest.app_dir)
    _ensure_on_sys_path(app_manifest.app_dir.parent)

    # 1) Ensure 'apps' is a namespace package pointing at app_config.app_dir
    _ensure_namespace_package(app_manifest.app_dir, pkg_name)

    # 2) Compute canonical module name from relative path under app_dir
    mod_name = _module_name_for(app_manifest.app_dir, module_path, pkg_name)

    # 3) Import or reload the module by canonical name
    if mod_name in sys.modules:  # noqa: SIM108
        module = importlib.reload(sys.modules[mod_name])
    else:
        module = importlib.import_module(mod_name)

    try:
        app_class = getattr(module, class_name)
    except AttributeError:
        raise AttributeError(f"Class {class_name} not found in module {mod_name} ({module_path})") from None

    if not issubclass(app_class, App | AppSync):
        raise TypeError(f"Class {class_name} is not a subclass of App or AppSync")

    if app_class._import_exception:
        raise app_class._import_exception  # surface subclass init errors

    LOADED_CLASSES[cache_key] = app_class
    return app_class


def _ensure_namespace_package(root: Path, pkg_name: str) -> None:
    """Ensure a namespace package rooted at `root` is importable as `pkg_name`.

    Args:
      root (Path): Directory to treat as the root of the namespace package.
      pkg_name (str): The package name to use (e.g. 'apps')

    Returns:
      None

    - Creates/updates sys.modules[pkg_name] as a namespace package.
    - Adds `root` to submodule_search_locations so 'pkg_name.*' resolves under this directory.
    """

    root = root.resolve()
    if pkg_name in sys.modules and hasattr(sys.modules[pkg_name], "__path__"):
        ns_pkg = sys.modules[pkg_name]
        # extend search locations if necessary
        if str(root) not in ns_pkg.__path__:
            ns_pkg.__path__.append(str(root))
        return

    # Synthesize a namespace package
    spec = importlib.machinery.ModuleSpec(pkg_name, loader=None, is_package=True)
    ns_pkg = importlib.util.module_from_spec(spec)
    ns_pkg.__path__ = [str(root)]
    sys.modules[pkg_name] = ns_pkg


def _module_name_for(app_dir: Path, full_path: Path, pkg_name: str) -> str:
    """
    Map a file within app_dir to a stable module name under the 'apps' package.

    Args:
      app_dir (Path): The root directory containing apps (e.g. /path/to/apps)
      full_path (Path): The full path to the app module file (e.g. /path/to/apps/my_app.py)
      pkg_name (str): The package name to use (e.g. 'apps')

    Returns:
      str: The dotted module name (e.g. 'apps.my_app')

    Examples:
      app_dir=/path/to/apps
        /path/to/apps/my_app.py         -> apps.my_app
        /path/to/apps/notifications/email_digest.py -> apps.notifications.email_digest
    """
    app_dir = app_dir.resolve()
    full_path = full_path.resolve()
    rel = full_path.relative_to(app_dir).with_suffix("")  # drop .py
    parts = list(rel.parts)
    return ".".join([pkg_name, *parts])


def _ensure_on_sys_path(p: Path) -> None:
    """Ensure the given path is on sys.path for module resolution.

    Args:
      p (Path): Directory to add to sys.path

    Note:
      - Will not add root directories (with <=1 parts) for safety.
    """

    p = p.resolve()
    if len(p.parts) <= 1:
        LOGGER.warning("Refusing to add root directory %s to sys.path", p)
        return

    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
