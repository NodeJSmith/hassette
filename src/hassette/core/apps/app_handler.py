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


def _is_timeout(exc: BaseException) -> bool:
    """Robustly detect anyio.fail_after timeouts across versions."""
    # anyio 3: TimeoutCancellationError; anyio 4: TimeoutError
    name = exc.__class__.__name__
    return isinstance(exc, TimeoutError) or name in {"TimeoutCancellationError"}


def _manifest_key(app_name: str, index: int) -> str:
    # Human-friendly identifier for logs; not used as dict key.
    return f"{app_name}[{index}]"


class _AppHandler(Resource):
    """Manages the lifecycle of apps in Hassette.

    - Deterministic storage: apps[app_name][index] -> App
    - Tracks per-app failures in failed_apps for observability
    """

    def __init__(self, hassette: "Hassette") -> None:
        super().__init__(hassette)

        self.apps_config = deepcopy(self.hassette.config.apps)
        """Copy of Hassette's config apps"""

        self.active_apps_config: dict[str, AppManifest] = {}
        """Apps that are enabled"""

        self.apps: dict[str, dict[int, App]] = defaultdict(dict)
        """Running apps"""

        self.failed_apps: dict[str, list[tuple[int, Exception]]] = defaultdict(list)
        """Apps we could not start/failed to start"""

    async def initialize(self) -> None:
        """Start handler and initialize configured apps."""
        await self.initialize_apps()
        await super().initialize()

    async def shutdown(self) -> None:
        """Shutdown all app instances gracefully."""
        self.logger.debug("Stopping '%s' %s", self.class_name, self.role)

        # Flatten and iterate
        for app_name, instances in list(self.apps.items()):
            for index, app_instance in list(instances.items()):
                ident = _manifest_key(app_name, index)
                try:
                    with anyio.fail_after(FAIL_AFTER_SECONDS):
                        await app_instance.shutdown()
                    self.logger.info("App %s shutdown successfully", ident)
                except Exception:
                    self.logger.exception("Failed to shutdown app %s", ident)

        self.apps.clear()
        self.failed_apps.clear()
        await super().shutdown()

    def get(self, app_name: str, index: int = 0) -> App | None:
        """Get a specific app instance if running."""
        return self.apps.get(app_name, {}).get(index)

    def all(self) -> list[App]:
        """All running app instances."""
        return [inst for group in self.apps.values() for inst in group.values()]

    async def stop_app(self, app_name: str) -> None:
        """Stop and remove all instances for a given app_name."""
        instances = self.apps.pop(app_name, None)
        if not instances:
            self.logger.warning("Cannot stop app %s, not found", app_name)
            return
        self.logger.info("Stopping %d instance of %s", len(instances), app_name)
        for index, inst in instances.items():
            ident = _manifest_key(app_name, index)
            try:
                with anyio.fail_after(FAIL_AFTER_SECONDS):
                    await inst.shutdown()
                self.logger.info("Stopped app %s", ident)
            except Exception:
                self.logger.exception("Failed to stop app %s", ident)

    async def reload_app(self, app_name: str) -> None:
        """Stop and reinitialize a single app by name (based on current config)."""
        self.logger.info("Reloading app %s", app_name)

        await self.stop_app(app_name)
        # Initialize only that app from the current config if present and enabled
        manifest = self.active_apps_config.get(app_name)
        if not manifest:
            if manifest := self.apps_config.get(app_name):
                self.logger.warning("Cannot reload app %s, not enabled", app_name)
                return
            self.logger.warning("Cannot reload app %s, not found", app_name)
            return

        assert manifest is not None, "Manifest should not be None"

        self._create_app_instances(app_name, manifest)
        await self._initialize_app_instances(app_name, manifest)

    async def initialize_apps(self) -> None:
        self.logger.debug(
            "Found %d apps in configuration: %s",
            len(self.apps_config),
            list(self.apps_config.keys()),
        )

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
            self.apps, self.failed_apps = await self._initialize_apps(self.apps_config)
        except Exception as e:
            self.logger.exception("Failed to initialize apps")
            await self.handle_crash(e)
            raise

    async def _initialize_apps(self, apps_config: dict[str, "AppManifest"]):
        """Initialize all configured and enabled apps."""

        # Rebuild each app_name from manifest (stop any old instances first)
        for app_name, app_manifest in apps_config.items():
            if not app_manifest.enabled:
                self.logger.debug("App %s is disabled, skipping initialization", app_name)
                continue
            self.active_apps_config[app_name] = app_manifest

        only_apps: list[type[App[AppConfig]]] = []
        for app_manifest in self.active_apps_config.values():
            try:
                app_class = load_app_class(app_manifest)
                if app_class._only:
                    only_apps.append(app_class)
            except (UndefinedUserConfigError, InvalidInheritanceError):
                self.logger.error(
                    "Failed to load app %s due to bad configuration - check previous logs for details",
                    app_manifest.display_name,
                )
            except Exception:
                self.logger.exception("Failed to load app class for %s", app_manifest.display_name)

        if only_apps:
            if len(only_apps) > 1:
                names = ", ".join(app.__name__ for app in only_apps)
                raise RuntimeError(f"Multiple apps marked as only: {names}")
            only_app = only_apps[0]
            self.logger.warning("App %s is marked as only, skipping all others", only_app.__name__)
            self.active_apps_config = {
                name: manifest
                for name, manifest in self.active_apps_config.items()
                if load_app_class(manifest) is only_app
            }

        for app_name, app_manifest in self.active_apps_config.items():
            try:
                self._create_app_instances(app_name, app_manifest)
                await self._initialize_app_instances(app_name, app_manifest)
            except (UndefinedUserConfigError, InvalidInheritanceError):
                self.logger.error(
                    "Failed to load app %s due to bad configuration - check previous logs for details",
                    app_name,
                )
                continue
            except Exception:
                self.logger.exception("Failed to load app class for %s", app_name)
                continue

        return self.apps, self.failed_apps

    def _create_app_instances(self, app_name: str, app_manifest: "AppManifest") -> None:
        """Create app instances from a manifest, validating config.

        Args:
            app_name (str): The name of the app.
            app_manifest (AppManifest): The manifest containing configuration.
        """

        app_class = load_app_class(app_manifest)

        class_name = app_class.__name__
        app_class.app_manifest = app_manifest
        app_class.logger = getLogger(f"hassette.{app_class.__name__}")

        # Normalize to list-of-configs; TOML supports both single dict and list of dicts.
        settings_cls = app_class.app_config_cls
        user_configs = app_manifest.user_config
        config_list = user_configs if isinstance(user_configs, list) else [user_configs]

        for idx, config in enumerate(config_list):
            ident = _manifest_key(app_name, idx)
            try:
                validated = settings_cls.model_validate(config)
                app_instance = app_class(self.hassette, app_config=validated, index=idx)
                self.apps[app_name][idx] = app_instance
            except Exception as e:
                self.logger.exception("Failed to validate/init config for %s (%s)", ident, class_name)
                self.failed_apps[app_name].append((idx, e))
                continue

    async def _initialize_app_instances(self, app_name: str, app_manifest: "AppManifest") -> None:
        """Initialize all instances of a given app_name.

        Args:
          app_name (str): The name of the app.
          app_manifest (AppManifest): The manifest containing configuration.
        """

        class_name = app_manifest.class_name
        for idx, app_instance in self.apps.get(app_name, {}).items():
            ident = _manifest_key(app_name, idx)

            try:
                with anyio.fail_after(FAIL_AFTER_SECONDS):
                    await app_instance.initialize()
                self.logger.info("App %s (%s) initialized successfully", ident, class_name)
            except Exception as e:
                if _is_timeout(e):
                    self.logger.exception("Timed out while starting app %s (%s)", ident, class_name)
                else:
                    self.logger.exception("Failed to start app %s (%s)", ident, class_name)
                app_instance.status = ResourceStatus.STOPPED
                self.failed_apps.setdefault(app_name, []).append((idx, e))


def load_app_class(app_manifest: "AppManifest") -> "type[App[AppConfig]]":
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
