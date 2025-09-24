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

from hassette.config.core_config import HassetteConfig
from hassette.core.apps.app import App, AppSync
from hassette.core.classes import Resource
from hassette.core.enums import ResourceStatus
from hassette.core.topics import HASSETTE_EVENT_FILE_WATCHER
from hassette.exceptions import InvalidInheritanceError, UndefinedUserConfigError

if typing.TYPE_CHECKING:
    from hassette.config.app_manifest import AppManifest
    from hassette.core.apps.app_config import AppConfig
    from hassette.core.core import Hassette
    from hassette.core.events import HassetteFileWatcherEvent

LOGGER = getLogger(__name__)
FAIL_AFTER_SECONDS = 10
LOADED_CLASSES: "dict[tuple[str, str], type[App[AppConfig]]]" = {}
ROOT_PATH = "root"
USER_CONFIG_PATH = "user_config"


def _manifest_key(app_name: str, index: int) -> str:
    # Human-friendly identifier for logs; not used as dict key.
    return f"{app_name}[{index}]"


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
        self.hassette.bus.on(topic=HASSETTE_EVENT_FILE_WATCHER, handler=self.handle_change_event)

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

    async def _handle_new_apps(self, apps: set[str]) -> None:
        """Start any apps that are in config but not currently running."""
        if not apps:
            return

        self.logger.info("Starting %d new apps: %s", len(apps), list(apps))
        try:
            await self._initialize_apps(apps)
        except Exception as e:
            self.logger.exception("Failed to start new apps")
            await self.handle_crash(e)
            raise

    async def reload_app(self, app_key: str, force_reload: bool = False) -> None:
        """Stop and reinitialize a single app by key (based on current config)."""
        self.logger.info("Reloading app %s", app_key)
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

    async def initialize_apps(self) -> None:
        if not (await self.hassette.wait_for_resources_running([self.hassette._websocket])):
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

    async def _initialize_apps(self, apps: set[str] | None = None) -> None:
        """Initialize all configured and enabled apps."""

        await self._set_only_app()

        apps = apps if apps is not None else set(self.active_apps_config.keys())

        for app_key in apps:
            app_manifest = self.active_apps_config.get(app_key)
            if not app_manifest:
                self.logger.debug("Skipping disabled or unknown app %s", app_key)
                continue
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
        try:
            app_class = load_app_class(app_manifest, force_reload=force_reload)
        except Exception as e:
            self.logger.exception("Failed to load app class for %s", app_key)
            self.failed_apps[app_key].append((0, e))
            return

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

    async def handle_change_event(self, event: "HassetteFileWatcherEvent") -> None:
        """Handle changes detected by the watcher."""
        await self.handle_changes(event.payload.data.changed_file_path)

    async def refresh_config(self) -> tuple[dict[str, "AppManifest"], dict[str, "AppManifest"]]:
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

        orphans, new_apps, reimport_apps, reload_apps = self._calculate_app_changes(
            original_apps_config, curr_apps_config, changed_file_path
        )
        await self._handle_removed_apps(orphans)
        await self._handle_new_apps(new_apps)
        await self._reload_apps_due_to_file_change(reimport_apps)
        await self._reload_apps_due_to_config(reload_apps)

        prev_only_app = self.only_app

        # recalculate only_app in case it changed
        await self._set_only_app()

        # re-run orphan and start checks in case only_app changed
        if prev_only_app != self.only_app:
            if self.only_app:
                # stop all except only_app
                orphans = {k for k in self.apps if k != self.only_app}
                await self._handle_removed_apps(orphans)
                await self._handle_new_apps({self.only_app} if self.only_app in curr_apps_config else set())
            else:
                # start all enabled apps
                await self.initialize_apps()

    def _calculate_app_changes(
        self,
        original_apps_config: dict[str, "AppManifest"],
        curr_apps_config: dict[str, "AppManifest"],
        changed_path: Path | None,
    ) -> tuple[set[str], set[str], set[str], set[str]]:
        """Return 4 sets of app keys: (orphans, new_apps, reimport_apps, reload_apps).

        Args:
            original_apps_config (dict[str, AppManifest]): The original apps configuration.
            curr_apps_config (dict[str, AppManifest]): The current apps configuration.
            changed_path (Path | None): The path of the file that changed, if any.

        Returns:
            tuple[set[str], set[str], set[str], set[str]]: A tuple containing four sets:
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

        self.logger.info("Apps removed from config: %s", orphans)
        await self.stop_orphans(orphans)

    async def _reload_apps_due_to_file_change(self, apps: set[str]) -> None:
        if not apps:
            return

        self.logger.debug("Apps to reimport due to file change: %s", apps)
        for app_key in apps:
            await self.reload_app(app_key, force_reload=True)

    async def _reload_apps_due_to_config(self, apps: set[str]) -> None:
        if not apps:
            return

        self.logger.info("Apps to reload due to config changes: %s", apps)
        for app_key in apps:
            await self.reload_app(app_key)


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
