"""App factory for creating app instances with config validation."""

from logging import getLogger
from typing import TYPE_CHECKING

from hassette.utils.app_utils import (
    class_already_loaded,
    class_failed_to_load,
    get_class_load_error,
    get_loaded_class,
    load_app_class_from_manifest,
)
from hassette.utils.exception_utils import get_short_traceback

if TYPE_CHECKING:
    from hassette import AppConfig, Hassette
    from hassette.app import App
    from hassette.config.classes import AppManifest
    from hassette.core.app_registry import AppRegistry

LOGGER = getLogger(__name__)


class AppFactory:
    """Creates app instances from manifests with config validation.

    Handles class loading, caching, and Pydantic validation.
    """

    def __init__(self, hassette: "Hassette", registry: "AppRegistry") -> None:
        self.hassette = hassette
        self.registry = registry
        self.logger = getLogger(f"{__name__}.AppFactory")

    def create_instances(
        self,
        app_key: str,
        manifest: "AppManifest",
        force_reload: bool = False,
    ) -> None:
        """Create all app instances for a manifest and register them.

        Args:
            app_key: The app key from configuration
            manifest: The app manifest with config
            force_reload: Whether to force reload the class
        """
        # Try to load the class
        app_class = self._load_class(app_key, manifest, force_reload)
        if app_class is None:
            # Class loading failed - record failure at index 0
            load_error = self._get_load_error(manifest)
            self.registry.record_failure(app_key, 0, load_error)
            return

        # Set manifest on class
        app_class.app_manifest = manifest
        app_configs = self._normalize_configs(manifest.app_config)

        # Create instances
        for idx, config in enumerate(app_configs):
            instance_name = config.get("instance_name")
            if not instance_name:
                self.registry.record_failure(
                    app_key, idx, ValueError(f"App {app_key} instance {idx} is missing instance_name")
                )
                continue

            try:
                validated = app_class.app_config_cls.model_validate(config)
                app_instance = app_class(
                    hassette=self.hassette,
                    app_config=validated,
                    index=idx,
                )
                self.registry.register_app(app_key, idx, app_instance)
            except Exception as e:
                self.logger.error(
                    "Failed to validate/init config for %s (%s):\n%s",
                    instance_name,
                    app_class.__name__,
                    get_short_traceback(),
                )
                self.registry.record_failure(app_key, idx, e)

    def _load_class(
        self,
        app_key: str,
        manifest: "AppManifest",
        force_reload: bool,
    ) -> "type[App[AppConfig]] | None":
        """Load the app class, handling caching and errors."""
        already_loaded = class_already_loaded(manifest.full_path, manifest.class_name)
        already_failed = class_failed_to_load(manifest.full_path, manifest.class_name)

        if force_reload or (not already_loaded and not already_failed):
            try:
                return load_app_class_from_manifest(manifest, force_reload=force_reload)
            except Exception:
                self.logger.error(
                    "Failed to load app class for '%s':\n%s",
                    app_key,
                    get_short_traceback(),
                )
                return None

        if already_failed:
            self.logger.debug(
                "Cannot create app instances for '%s' because class failed to load previously",
                app_key,
            )
            return None

        return get_loaded_class(manifest.full_path, manifest.class_name)

    def _get_load_error(self, manifest: "AppManifest") -> Exception:
        """Get the error that caused class loading to fail."""
        if class_failed_to_load(manifest.full_path, manifest.class_name):
            return get_class_load_error(manifest.full_path, manifest.class_name)
        return RuntimeError(f"Unknown error loading class for {manifest.class_name}")

    @staticmethod
    def _normalize_configs(app_config: dict | list[dict] | None) -> list[dict]:
        """Ensure app_config is a list of dicts."""
        if app_config is None:
            return []
        if isinstance(app_config, dict):
            return [app_config]
        return list(app_config)

    def check_only_app_decorator(self, manifest: "AppManifest", *, force_reload: bool = False) -> bool:
        """Check if an app class has the only_app decorator.

        Args:
            manifest: The app manifest to check
            force_reload: Whether to force reload the class from disk

        Returns:
            True if the app has the only_app decorator, False otherwise
        """
        if not force_reload and class_failed_to_load(manifest.full_path, manifest.class_name):
            return False

        try:
            if force_reload:
                app_class = load_app_class_from_manifest(manifest, force_reload=True)
            elif class_already_loaded(manifest.full_path, manifest.class_name):
                app_class = get_loaded_class(manifest.full_path, manifest.class_name)
            else:
                app_class = load_app_class_from_manifest(manifest)
            return getattr(app_class, "_only_app", False)
        except Exception:
            self.logger.error(
                "Failed to check only_app for '%s':\n%s",
                manifest.display_name,
                get_short_traceback(),
            )
            return False
