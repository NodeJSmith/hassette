"""App factory for creating app instances with config validation."""

from logging import getLogger
from typing import TYPE_CHECKING

from hassette.schemas.app_config_shape import normalize_app_config
from hassette.utils.app_utils import (
    class_already_loaded,
    class_failed_to_load,
    get_class_load_error,
    get_loaded_class,
    is_valid_instance_name,
    load_app_class_from_manifest,
)
from hassette.utils.exception_utils import get_short_traceback

if TYPE_CHECKING:
    from hassette import AppConfig, Hassette
    from hassette.app import App
    from hassette.config.classes import AppManifest
    from hassette.core.app_registry import AppRegistry


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
    ) -> set[int]:
        """Create all app instances for a manifest and register them.

        Returns the set of indices that were actually created. Indices that already have a
        live registry entry are skipped — callers use this to initialize only the new instances.

        Args:
            app_key: The app key from configuration
            manifest: The app manifest with config
            force_reload: Whether to force reload the class. Ignored (treated as False) if any
                instance of this app_key is already running (configured index or not) -- see
                reload_app() to force a reload onto instances that are already running.
        """
        app_configs = self.normalize_configs(manifest.app_config)

        # Which configured indices already have a live registry entry -- computed once and
        # reused below by the class-load-failure target lookup and the per-index creation loop,
        # so both agree on what "already running" means for this call instead of re-deriving it
        # independently. Deliberately scoped to the *current* config's index range: creation and
        # failure-target selection only ever act on configured indices.
        live_indices = {idx for idx in range(len(app_configs)) if self.registry.get(app_key, idx) is not None}

        # A forced reload is unsafe to combine with any already-running instance of this
        # app_key: load_class() would reload the shared module/class before the per-index guard
        # below preserves the live instance, leaving it bound to the pre-reload class while any
        # newly created sibling gets the post-reload one -- two class versions serving one
        # app_key at once. And when every instance is already live, the reload has no instance
        # left to apply to, so it would just mutate the module/class cache for nothing.
        # Unlike live_indices above, this check is NOT scoped to the current config's index
        # range: prune_stale_failed_indices() (called by _start_app_unlocked() before this)
        # only prunes stale *failed* entries, never running ones, so a running orphan at an
        # index the config no longer covers (e.g. after a config shrink) can still be live here.
        # Missing it would let force_reload slip through and reproduce the exact class-version
        # split this guard exists to prevent, just via an out-of-range instance instead of an
        # in-range one. Only reload when nothing for this app_key is currently running at all;
        # reload_app() is the supported way to get a fresh class onto instances that are already
        # up (it stops them first, so create_instances() runs against an empty slate — see its
        # "no-op on the reload_app() path" note below).
        if force_reload and self.registry.get_running_apps(app_key):
            self.logger.debug(
                "Ignoring force_reload for '%s' -- instance(s) already running; use reload_app() "
                "to recreate them with a freshly-reloaded class",
                app_key,
            )
            force_reload = False

        # Try to load the class
        app_class = self.load_class(app_key, manifest, force_reload)
        if app_class is None:
            # Class loading failed — this affects every configured index (one shared class
            # serves all instances of this app_key), but we only ever record one representative
            # failure. Record it against the first configured index that isn't already running,
            # not always index 0: if index 0 is preserved from a prior successful start, blindly
            # recording there would both overwrite its live entry and leave a genuinely-failed,
            # unstarted sibling index unreported (looking like an ordinary stopped index instead
            # of FAILED). If every configured index already has a live entry, there's no
            # unstarted index left to report against, so skip recording entirely.
            load_error = self.get_load_error(manifest)
            target_index = next((idx for idx in range(len(app_configs)) if idx not in live_indices), None)
            if target_index is not None:
                self.registry.record_failure(app_key, target_index, load_error)
            return set()

        # Create instances, skipping indices that already have a live registry entry.
        # Without this guard, a second start_app() call silently overwrites running instances
        # via register_app() (which replaces any prior entry at that index), orphaning the
        # originals' listeners, scheduler jobs, and tasks. Callers that want a fresh instance
        # should use reload_app(), which stops before recreating. A no-op on the reload_app()
        # path: _stop_app_unlocked() already removed all entries before create_instances() runs.
        # Mirrors the per-index guard in start_instance() (#1688).
        created: set[int] = set()
        for idx, config in enumerate(app_configs):
            if idx in live_indices:
                self.logger.debug("Index %d of app %s is already running — skipping", idx, app_key)
                continue
            self.create_single_instance(app_key, manifest, idx, config, app_class)
            created.add(idx)
        return created

    def create_single_instance(
        self,
        app_key: str,
        manifest: "AppManifest",
        index: int,
        config_dict: dict,
        app_class: "type[App[AppConfig]]",
    ) -> None:
        """Create and register a single app instance at the given index.

        Args:
            app_key: The app key from configuration
            manifest: The app manifest with config
            index: The instance index this config corresponds to
            config_dict: The raw config dict for this instance
            app_class: The already-loaded app class to instantiate
        """
        instance_name = config_dict.get("instance_name")
        if not is_valid_instance_name(instance_name):
            self.registry.record_failure(
                app_key, index, ValueError(f"App {app_key} instance {index} is missing instance_name")
            )
            return

        try:
            validated = app_class.app_config_cls.model_validate(config_dict)
            app_instance = app_class(
                hassette=self.hassette,
                app_config=validated,
                index=index,
                app_key=app_key,
                app_manifest=manifest,
            )
            self.registry.register_app(app_key, index, app_instance)
        except Exception as exc:
            self.logger.error(
                "Failed to validate/init config for %s (%s):\n%s",
                instance_name,
                app_class.__name__,
                get_short_traceback(),
            )
            self.registry.record_failure(app_key, index, exc)

    def load_class(
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

    def get_load_error(self, manifest: "AppManifest") -> Exception:
        """Get the error that caused class loading to fail."""
        if class_failed_to_load(manifest.full_path, manifest.class_name):
            return get_class_load_error(manifest.full_path, manifest.class_name)
        return RuntimeError(f"Unknown error loading class for {manifest.class_name}")

    @staticmethod
    def normalize_configs(app_config: dict | list[dict] | None) -> list[dict]:
        """Ensure app_config is a list of dicts."""
        return normalize_app_config(app_config)
