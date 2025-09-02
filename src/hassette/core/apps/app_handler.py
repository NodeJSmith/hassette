import asyncio
import hashlib
import importlib.util
import sys
import typing
from logging import getLogger

import anyio

from hassette.core.apps.app import App
from hassette.core.classes import Resource
from hassette.core.enums import ResourceStatus
from hassette.exceptions import InvalidInheritanceError, UndefinedUserConfigError

if typing.TYPE_CHECKING:
    from hassette.config.app_manifest import AppManifest
    from hassette.core.apps.app_config import AppConfig
    from hassette.core.core import Hassette

FAIL_AFTER_SECONDS = 10


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
        self.hassette = hassette

        # Running instances: { app_name: { index: App } }
        self.apps: dict[str, dict[int, App]] = {}

        # Failures captured during init: { app_name: [ (index, Exception) ] }
        self.failed_apps: dict[str, list[tuple[int, Exception]]] = {}

        # Cache: loaded classes keyed by (full_path, class_name)
        self._loaded_classes: dict[tuple[str, str], type[App[AppConfig]]] = {}

    async def initialize(self) -> None:
        """Start handler and initialize configured apps."""
        await super().initialize()
        await self.initialize_apps()

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

    # ---------- Public-ish helpers (handy in tests / hot-reload pathways) ----------

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
            return
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
        await self.stop_app(app_name)
        # Initialize only that app from the current config if present and enabled
        manifest = self.hassette.config.apps.get(app_name)
        if manifest and manifest.enabled:
            await self._initialize_single_app(app_name, manifest)

    # ---------- Core initialization logic ----------

    async def initialize_apps(self) -> None:
        """Initialize all configured and enabled apps."""
        apps_config = self.hassette.config.apps
        self.logger.debug("Found %d apps in configuration: %s", len(apps_config), list(apps_config.keys()))

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

        if not apps_config:
            self.logger.info("No apps configured, skipping initialization")
            return

        # Rebuild each app_name from manifest (stop any old instances first)
        for app_name, app_manifest in apps_config.items():
            if not app_manifest.enabled:
                self.logger.debug("App %s is disabled, skipping initialization", app_name)
                # If previously running, stop it
                if app_name in self.apps:
                    await self.stop_app(app_name)
                continue

            await self.stop_app(app_name)
            await self._initialize_single_app(app_name, app_manifest)

    async def _initialize_single_app(self, app_name: str, app_manifest: "AppManifest") -> None:
        """Initialize all instances (configs) for a single app."""
        try:
            app_class = self._load_app_class(app_manifest)
        except (UndefinedUserConfigError, InvalidInheritanceError):
            self.logger.error(
                "Failed to load app %s due to bad configuration - check previous logs for details", app_name
            )
            return
        except Exception:
            self.logger.exception("Failed to load app class for %s", app_name)
            return

        class_name = app_class.__name__
        app_class.app_manifest_cls = app_manifest
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
                self.apps.setdefault(app_name, {})[idx] = app_instance
            except Exception as e:
                self.logger.exception("Failed to validate/init config for %s (%s)", ident, class_name)
                self.failed_apps.setdefault(app_name, []).append((idx, e))
                continue

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

    # ---------- Module loading ----------

    def _load_app_class(self, app_config: "AppManifest") -> "type[App[AppConfig]]":
        """Dynamically load the app class from the specified module.

        Uses a collision-proof module key per file path so multiple classes
        with the same name from different files don't stomp each other.
        """
        module_path = str(app_config.get_full_path())  # resolves path, validates presence
        class_name = app_config.class_name

        if not module_path or not class_name:
            raise ValueError(f"App {app_config.display_name} is missing filename or class_name")

        cache_key = (module_path, class_name)
        if cache_key in self._loaded_classes:
            return self._loaded_classes[cache_key]

        # Unique module key based on path hash + class name
        digest = hashlib.sha1(module_path.encode("utf-8")).hexdigest()
        module_key = f"hassette_apps.{digest}.{class_name}"

        spec = importlib.util.spec_from_file_location(module_key, module_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load module {module_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_key] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]

        try:
            app_class = getattr(module, class_name)
        except AttributeError as e:
            raise AttributeError(f"Class {class_name} not found in module {module_path}") from e

        if not issubclass(app_class, App):
            raise TypeError(f"Class {class_name} is not a subclass of App")

        # If subclass import failed at class definition time, surface it
        if getattr(app_class, "_import_exception", None):
            raise app_class._import_exception  # type: ignore[misc]

        self._loaded_classes[cache_key] = app_class
        return app_class
