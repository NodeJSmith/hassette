"""App factory for creating app instances with config validation."""

import inspect
from difflib import get_close_matches
from logging import getLogger
from typing import TYPE_CHECKING
from warnings import warn

from pydantic import AliasChoices, AliasPath
from pydantic.fields import FieldInfo

from hassette.app.app_config import AppConfig
from hassette.core.app_lifecycle_common import ALREADY_RUNNING_REASON, CLASS_LOAD_FAILED_PREFIX, failure_reason
from hassette.schemas.app_config_shape import INSTANCE_NAME_KEY, configured_instance_names, normalize_app_config
from hassette.utils.app_utils import cached_load_error, load_app_class_from_manifest
from hassette.utils.exception_utils import get_short_traceback

SUGGESTION_CUTOFF = 0.5
"""``difflib`` similarity a declared key needs to be offered as a "did you mean" suggestion.

Looser than difflib's 0.6 default: a wrong guess costs a glance, a missing one leaves the user hunting."""

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.app import App
    from hassette.config.classes import AppManifest
    from hassette.core.app_lifecycle_common import ActionOutcomes
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
        *,
        outcomes: "ActionOutcomes",
    ) -> "dict[str, App[AppConfig] | Exception]":
        """Create the app instances for a manifest that aren't live or flagged; writes nothing to the registry.

        Returns a result for each name it created or tried to: its new ``App``, or the exception that stopped
        it. The one exception is a class that fails to load: that fails every name left to create in
        ``outcomes``, but is returned under one representative name only, the first name left to create. The
        caller writes each result's status (NOT_STARTED with the ``App``, FAILED with the exception) and
        initializes only the new instances.

        Names that already have a live registry entry are skipped and recorded as succeeded ("already
        running"). Names flagged as needing a hassette restart are skipped too, and recorded as refused; this
        logs nothing for them, so a caller with no response to carry the refusal logs it (``log_refusals``).
        When no configured name is left to create, the class isn't loaded.

        Args:
            app_key: The app key from configuration
            manifest: The app manifest with config
            force_reload: Whether to re-import the app's module if its file changed. Ignored while any
                instance of this app_key is live (see ``load_class``); reload_app() stops them first.
            outcomes: The request's outcomes; must target every configured name.
        """
        # A flagged name's old instance may still be running work, so no replacement is created over it
        # until hassette restarts. Its siblings are unaffected. When nothing is left to create (every name
        # live or flagged), the class isn't loaded either, so a refused app is never re-imported and records
        # no class-load failure. Deliberately scoped to the *current* config: creation and failure-target
        # selection only ever act on configured names.
        to_create: list[str] = []
        for name in configured_instance_names(manifest.app_config):
            if self.registry.get(app_key, name) is not None:
                self.logger.debug("Instance %s of app %s is already running — skipping", name, app_key)
                outcomes.succeeded(name, ALREADY_RUNNING_REASON)
                continue
            if (refusal := self.registry.refusal_reason(app_key, name)) is not None:
                outcomes.refused(name, refusal)
                continue
            to_create.append(name)
        if not to_create:
            return {}

        app_class = self.load_class(app_key, manifest, force_reload)
        if app_class is None:
            # Class loading failed — this affects every configured instance (one shared class
            # serves all instances of this app_key), but only one representative failure is returned.
            # It goes to the first configured name that is neither running nor flagged: if the first
            # name is preserved from a prior successful start, failing it would both overwrite its live
            # entry and leave a genuinely-failed, unstarted sibling unreported (looking like an ordinary
            # stopped instance instead of FAILED). The request's outcomes fail every name left to create,
            # naming the shared cause.
            load_error = self.get_load_error(manifest)
            for name in to_create:
                outcomes.failed(name, f"{CLASS_LOAD_FAILED_PREFIX}{failure_reason(load_error)}")
            return {to_create[0]: load_error}

        # Create only the names in to_create: live and flagged ones were skipped above.
        # Without the live-instance skip, a second start_app() call silently overwrites running instances
        # (a NOT_STARTED registration replaces any prior entry under that name), orphaning the
        # originals' listeners, scheduler jobs, and tasks. Callers that want a fresh instance
        # should use reload_app(), which stops before recreating. A no-op on the reload_app()
        # path: _stop_app_unlocked() already removed all entries before create_instances() runs.
        # Mirrors the per-instance guard in start_instance() (#1688).
        return {
            name: self.create_single_instance(app_key, manifest, name, app_class, outcomes=outcomes)
            for name in to_create
        }

    def create_single_instance(
        self,
        app_key: str,
        manifest: "AppManifest",
        instance_name: str,
        app_class: "type[App[AppConfig]]",
        *,
        outcomes: "ActionOutcomes",
    ) -> "App[AppConfig] | Exception":
        """Create a single app instance under the given name; writes nothing to the registry.

        A config that fails validation, or a constructor that raises, is recorded as the instance's
        failure in ``outcomes`` and returned.

        Args:
            app_key: The app key from configuration
            manifest: The app manifest with config
            instance_name: The name to create; ``manifest`` must configure it
            app_class: The already-loaded app class to instantiate
            outcomes: The request's outcomes

        Returns:
            The new instance, or the exception that stopped it.
        """
        # Each instance config's name is set by AppManifest.model_post_init (resolve_instance_name).
        configs = normalize_app_config(manifest.app_config)
        config_dict = {config[INSTANCE_NAME_KEY]: config for config in configs}[instance_name]

        try:
            validated = app_class.app_config_cls.model_validate(config_dict)
            if validated.instance_name != instance_name:
                # The registry files an app under its own name, and callers read it back by the configured one.
                raise ValueError(
                    f"{app_class.app_config_cls.__name__} resolved instance_name to {validated.instance_name!r} from "
                    f"{instance_name!r}; a config class must not alias or transform instance_name"
                )
            warn_unrecognized_config_keys(
                app_key=app_key,
                manifest=manifest,
                instance_name=instance_name,
                config_dict=config_dict,
                validated=validated,
            )
            return app_class(
                hassette=self.hassette,
                app_config=validated,
                app_key=app_key,
                app_manifest=manifest,
                debug_capture=self.registry.is_debug_captured(app_key, instance_name),
            )
        except Exception as exc:
            self.logger.error(
                "Failed to validate/init config for %s (%s):\n%s",
                instance_name,
                app_class.__name__,
                get_short_traceback(),
            )
            outcomes.failed(instance_name, failure_reason(exc))
            return exc

    def load_class(
        self,
        app_key: str,
        manifest: "AppManifest",
        force_reload: bool,
    ) -> "type[App[AppConfig]] | None":
        """Return the class for a new instance of ``app_key``, or None if it can't be loaded.

        While any instance of ``app_key`` is live (configured or an orphan) and was built from the manifest's
        file and class, a new instance gets that instance's class, forced or not, so one app key never runs
        classes from two imports of its module. A forced reload of a sibling app key from the same file can
        re-import the module, and a lone instance created afterwards would otherwise pick up the new class. A
        live instance built from another file or class name (a stop that failed during a manifest change)
        doesn't count, and the class comes from the loader. reload_app() stops every instance before
        recreating them, so it reaches the loader.
        """
        # Every live instance of a key was built from one class, so the first one speaks for all of them;
        # failed entries hold no App and aren't listed.
        if (live := next(iter(self.registry.get_live_apps(app_key).values()), None)) is not None and built_from(
            live, manifest
        ):
            if force_reload:
                self.logger.info(
                    "Reload of '%s' reuses the class its running instance(s) use, so the app file is not "
                    "re-imported; reload the whole app to pick up edits",
                    app_key,
                )
            return type(live)

        # The loader would re-raise this cached failure; checking here keeps it from being logged at ERROR again.
        if not force_reload and cached_load_error(manifest.full_path, manifest.class_name) is not None:
            self.logger.debug(
                "Cannot create app instances for '%s' because class failed to load previously",
                app_key,
            )
            return None

        try:
            return load_app_class_from_manifest(manifest, config=self.hassette.config, force_reload=force_reload)
        except Exception:
            self.logger.error(
                "Failed to load app class for '%s':\n%s",
                app_key,
                get_short_traceback(),
            )
            return None

    def get_load_error(self, manifest: "AppManifest") -> Exception:
        """Get the error that caused class loading to fail."""
        if (error := cached_load_error(manifest.full_path, manifest.class_name)) is not None:
            return error
        return RuntimeError(f"Unknown error loading class for {manifest.class_name}")


def built_from(app: "App[AppConfig]", manifest: "AppManifest") -> bool:
    """Whether ``app`` was created from the same file and class name ``manifest`` names."""
    built = app.app_manifest
    return built is not None and built.full_path == manifest.full_path and built.class_name == manifest.class_name


def warn_unrecognized_config_keys(
    app_key: str,
    manifest: "AppManifest",
    instance_name: str,
    config_dict: dict,
    validated: AppConfig,
) -> None:
    """Warn about config keys a typed ``AppConfig`` subclass absorbed as extras.

    ``AppConfig`` allows extras so a bare ``App[AppConfig]`` can take arbitrary config. A subclass
    that declares its own fields signals the app expects a known shape, so a leftover extra there
    is almost always a typo that would otherwise leave the intended field silently at its default.

    Only keys from the instance's own config are considered: pydantic-settings also folds
    unrecognized ``.env`` entries into ``model_extra``, and those are not the user's app config.
    """
    config_cls = type(validated)
    if not declares_own_fields(config_cls) or not validated.model_extra:
        return

    # ``instance_name`` is required under its literal name, so it can land in extras when an alias renames the field.
    unrecognized = [key for key in validated.model_extra if key in config_dict and key != INSTANCE_NAME_KEY]
    if not unrecognized:
        return

    accepted_keys = accepted_config_keys(config_cls)
    lines = []
    for key in unrecognized:
        if key in accepted_keys:
            # An accepted key left in extras either heads an ``AliasPath`` whose nested value is missing, or lost to
            # an earlier ``AliasChoices`` source present in the same config. Suggesting the key itself would be noise.
            lines.append(
                f"  {key!r} (accepted key, but its value went unused: check the nested path, or whether "
                "another alias for the same field took precedence)"
            )
            continue
        matches = get_close_matches(key, accepted_keys, n=1, cutoff=SUGGESTION_CUTOFF)
        lines.append(f"  {key!r} (did you mean {matches[0]!r}?)" if matches else f"  {key!r}")

    msg = (
        f"{config_cls.__name__} - {manifest.display_name} ({app_key}, instance {instance_name!r}) - "
        "Unrecognized configuration key(s) don't match any declared field:\n"
        + "\n".join(lines)
        + f"\nCheck the spelling against the fields declared on {config_cls.__name__}."
    )
    warn(msg, stacklevel=2)


def declares_own_fields(config_cls: type[AppConfig]) -> bool:
    """Whether a class not in ``AppConfig``'s own MRO declares a field, new or overriding an inherited one.

    Plain mixins count too, on either side of ``AppConfig`` in the bases: pydantic collects field
    annotations from every class in the MRO.
    """
    appconfig_mro = set(AppConfig.__mro__)
    own_classes = [klass for klass in config_cls.__mro__ if klass not in appconfig_mro]
    return any(name in config_cls.model_fields for klass in own_classes for name in inspect.get_annotations(klass))


def accepted_config_keys(config_cls: type[AppConfig]) -> list[str]:
    """Return the top-level keys ``config_cls`` actually populates its fields from.

    A field with an alias is populated by that alias, not by its attribute name, unless the model
    enables ``validate_by_name``; suggesting the attribute name there would point at another extra.
    """
    model_config = config_cls.model_config
    # Pydantic's two switches: aliases are honored unless ``validate_by_alias=False``; attribute names are
    # honored for aliased fields only when ``validate_by_name`` (or its older spelling ``populate_by_name``)
    # is set; an explicit ``validate_by_name`` wins over the legacy flag. Turning aliases off makes the attribute
    # name the only key that works.
    by_alias = model_config.get("validate_by_alias", True)
    by_name = model_config.get("validate_by_name", model_config.get("populate_by_name", False))

    keys: list[str] = []
    for name, field in config_cls.model_fields.items():
        aliases = field_alias_keys(field) if by_alias else []
        if not aliases:
            keys.append(name)  # unaliased field, or aliases disabled: the attribute name is the key
            continue
        keys.extend(aliases)
        if by_name:
            keys.append(name)
    return keys


def field_alias_keys(field: FieldInfo) -> list[str]:
    """Top-level config keys a field's validation alias (or plain alias) accepts."""
    alias = field.validation_alias if field.validation_alias is not None else field.alias
    choices = alias.choices if isinstance(alias, AliasChoices) else [alias]
    keys: list[str] = []
    for choice in choices:
        if isinstance(choice, str):
            keys.append(choice)
        elif isinstance(choice, AliasPath) and isinstance(choice.path[0], str):
            keys.append(choice.path[0])
    return keys
