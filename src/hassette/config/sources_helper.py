import logging
from copy import deepcopy
from pathlib import Path
from typing import Any, ClassVar

from pydantic_settings import BaseSettings
from pydantic_settings.sources import (
    ENV_FILE_SENTINEL,
    CliSettingsSource,
    DefaultSettingsSource,
    DotEnvSettingsSource,
    DotenvType,
    EnvSettingsSource,
    InitSettingsSource,
    PathType,
    PydanticBaseSettingsSource,
    SecretsSettingsSource,
    TomlConfigSettingsSource,
)

DEFAULT_PATH = Path()


LOGGER = logging.getLogger(__name__)


class HassetteTomlConfigSettingsSource(TomlConfigSettingsSource):
    def __init__(self, settings_cls: type[BaseSettings], toml_file: PathType | None = DEFAULT_PATH):
        self.toml_file_path = toml_file if toml_file != DEFAULT_PATH else settings_cls.model_config.get("toml_file")
        self.toml_data = self._read_files(self.toml_file_path)

        if "hassette" not in self.toml_data:
            # just let the standard class handle it
            super().__init__(settings_cls, self.toml_file_path)
            return

        LOGGER.info("Merging 'hassette' section from TOML config into top level")
        top_level_keys = set(self.toml_data.keys()) - {"hassette"}
        hassette_values = self.toml_data.pop("hassette")
        for key in top_level_keys.intersection(hassette_values.keys()):
            LOGGER.warning(
                "Key %r found in both top level and 'hassette' section of TOML config, "
                "the [hassette] value will be used",
                key,
            )

        self.toml_data.update(hassette_values)

        # need to call InitSettingSource directly, as super() expects a file path
        # as the second argument
        InitSettingsSource.__init__(self, settings_cls, self.toml_data)


class HassetteBaseSettings(BaseSettings):
    SETTINGS_SOURCES_DATA: ClassVar[dict[str, dict[str, Any]]] = {}
    FINAL_SETTINGS_SOURCES: ClassVar[dict[str, Any]] = {}
    init_kwargs: ClassVar[dict[str, Any]] = {}

    def _settings_build_values(
        self,
        init_kwargs: dict[str, Any],
        _case_sensitive: bool | None = None,
        _nested_model_default_partial_update: bool | None = None,
        _env_prefix: str | None = None,
        _env_file: DotenvType | None = None,
        _env_file_encoding: str | None = None,
        _env_ignore_empty: bool | None = None,
        _env_nested_delimiter: str | None = None,
        _env_nested_max_split: int | None = None,
        _env_parse_none_str: str | None = None,
        _env_parse_enums: bool | None = None,
        _cli_prog_name: str | None = None,
        _cli_parse_args: bool | list[str] | tuple[str, ...] | None = None,
        _cli_settings_source: CliSettingsSource[Any] | None = None,
        _cli_parse_none_str: str | None = None,
        _cli_hide_none_type: bool | None = None,
        _cli_avoid_json: bool | None = None,
        _cli_enforce_required: bool | None = None,
        _cli_use_class_docs_for_groups: bool | None = None,
        _cli_exit_on_error: bool | None = None,
        _cli_prefix: str | None = None,
        _cli_flag_prefix_char: str | None = None,
        _cli_implicit_flags: bool | None = None,
        _cli_ignore_unknown_args: bool | None = None,
        _cli_kebab_case: bool | None = None,
        _secrets_dir: PathType | None = None,
    ) -> dict[str, Any]:
        # custom checks
        if init_kwargs.get("config_file"):
            self.model_config["toml_file"] = init_kwargs.get("config_file")

        if init_kwargs.get("env_file"):
            _env_file = init_kwargs.get("env_file")

        # Determine settings config values
        case_sensitive = _case_sensitive if _case_sensitive is not None else self.model_config.get("case_sensitive")
        env_prefix = _env_prefix if _env_prefix is not None else self.model_config.get("env_prefix")
        nested_model_default_partial_update = (
            _nested_model_default_partial_update
            if _nested_model_default_partial_update is not None
            else self.model_config.get("nested_model_default_partial_update")
        )
        env_file = _env_file if _env_file != ENV_FILE_SENTINEL else self.model_config.get("env_file")
        env_file_encoding = (
            _env_file_encoding if _env_file_encoding is not None else self.model_config.get("env_file_encoding")
        )
        env_ignore_empty = (
            _env_ignore_empty if _env_ignore_empty is not None else self.model_config.get("env_ignore_empty")
        )
        env_nested_delimiter = (
            _env_nested_delimiter
            if _env_nested_delimiter is not None
            else self.model_config.get("env_nested_delimiter")
        )
        env_nested_max_split = (
            _env_nested_max_split
            if _env_nested_max_split is not None
            else self.model_config.get("env_nested_max_split")
        )
        env_parse_none_str = (
            _env_parse_none_str if _env_parse_none_str is not None else self.model_config.get("env_parse_none_str")
        )
        env_parse_enums = _env_parse_enums if _env_parse_enums is not None else self.model_config.get("env_parse_enums")

        cli_prog_name = _cli_prog_name if _cli_prog_name is not None else self.model_config.get("cli_prog_name")
        cli_parse_args = _cli_parse_args if _cli_parse_args is not None else self.model_config.get("cli_parse_args")
        cli_settings_source = (
            _cli_settings_source if _cli_settings_source is not None else self.model_config.get("cli_settings_source")
        )
        cli_parse_none_str = (
            _cli_parse_none_str if _cli_parse_none_str is not None else self.model_config.get("cli_parse_none_str")
        )
        cli_parse_none_str = cli_parse_none_str if not env_parse_none_str else env_parse_none_str  # noqa
        cli_hide_none_type = (
            _cli_hide_none_type if _cli_hide_none_type is not None else self.model_config.get("cli_hide_none_type")
        )
        cli_avoid_json = _cli_avoid_json if _cli_avoid_json is not None else self.model_config.get("cli_avoid_json")
        cli_enforce_required = (
            _cli_enforce_required
            if _cli_enforce_required is not None
            else self.model_config.get("cli_enforce_required")
        )
        cli_use_class_docs_for_groups = (
            _cli_use_class_docs_for_groups
            if _cli_use_class_docs_for_groups is not None
            else self.model_config.get("cli_use_class_docs_for_groups")
        )
        cli_exit_on_error = (
            _cli_exit_on_error if _cli_exit_on_error is not None else self.model_config.get("cli_exit_on_error")
        )
        cli_prefix = _cli_prefix if _cli_prefix is not None else self.model_config.get("cli_prefix")
        cli_flag_prefix_char = (
            _cli_flag_prefix_char
            if _cli_flag_prefix_char is not None
            else self.model_config.get("cli_flag_prefix_char")
        )
        cli_implicit_flags = (
            _cli_implicit_flags if _cli_implicit_flags is not None else self.model_config.get("cli_implicit_flags")
        )
        cli_ignore_unknown_args = (
            _cli_ignore_unknown_args
            if _cli_ignore_unknown_args is not None
            else self.model_config.get("cli_ignore_unknown_args")
        )
        cli_kebab_case = _cli_kebab_case if _cli_kebab_case is not None else self.model_config.get("cli_kebab_case")

        secrets_dir = _secrets_dir if _secrets_dir is not None else self.model_config.get("secrets_dir")

        # Configure built-in sources
        default_settings = DefaultSettingsSource(
            self.__class__,
            nested_model_default_partial_update=nested_model_default_partial_update,
        )
        init_settings = InitSettingsSource(
            self.__class__,
            init_kwargs=init_kwargs,
            nested_model_default_partial_update=nested_model_default_partial_update,
        )
        env_settings = EnvSettingsSource(
            self.__class__,
            case_sensitive=case_sensitive,
            env_prefix=env_prefix,
            env_nested_delimiter=env_nested_delimiter,
            env_nested_max_split=env_nested_max_split,
            env_ignore_empty=env_ignore_empty,
            env_parse_none_str=env_parse_none_str,
            env_parse_enums=env_parse_enums,
        )
        dotenv_settings = DotEnvSettingsSource(
            self.__class__,
            env_file=env_file,
            env_file_encoding=env_file_encoding,
            case_sensitive=case_sensitive,
            env_prefix=env_prefix,
            env_nested_delimiter=env_nested_delimiter,
            env_nested_max_split=env_nested_max_split,
            env_ignore_empty=env_ignore_empty,
            env_parse_none_str=env_parse_none_str,
            env_parse_enums=env_parse_enums,
        )

        file_secret_settings = SecretsSettingsSource(
            self.__class__,
            secrets_dir=secrets_dir,
            case_sensitive=case_sensitive,
            env_prefix=env_prefix,
        )
        # Provide a hook to set built-in sources priority and add / remove sources
        sources = (
            *self.settings_customise_sources(
                self.__class__,
                init_settings=init_settings,
                env_settings=env_settings,
                dotenv_settings=dotenv_settings,
                file_secret_settings=file_secret_settings,
            ),
            default_settings,
        )
        if not any(source for source in sources if isinstance(source, CliSettingsSource)):
            if isinstance(cli_settings_source, CliSettingsSource):
                sources = (cli_settings_source, *sources)
            elif cli_parse_args is not None:
                cli_settings = CliSettingsSource[Any](
                    self.__class__,
                    cli_prog_name=cli_prog_name,
                    cli_parse_args=cli_parse_args,
                    cli_parse_none_str=cli_parse_none_str,
                    cli_hide_none_type=cli_hide_none_type,
                    cli_avoid_json=cli_avoid_json,
                    cli_enforce_required=cli_enforce_required,
                    cli_use_class_docs_for_groups=cli_use_class_docs_for_groups,
                    cli_exit_on_error=cli_exit_on_error,
                    cli_prefix=cli_prefix,
                    cli_flag_prefix_char=cli_flag_prefix_char,
                    cli_implicit_flags=cli_implicit_flags,
                    cli_ignore_unknown_args=cli_ignore_unknown_args,
                    cli_kebab_case=cli_kebab_case,
                    case_sensitive=case_sensitive,
                )
                sources = (cli_settings, *sources)
        if sources:
            state: dict[str, Any] = {}
            states: dict[str, dict[str, Any]] = {}
            for source in sources:
                # hassette logging
                LOGGER.debug("Loading configuration from source: %s", source)
                if isinstance(source, PydanticBaseSettingsSource):
                    source._set_current_state(state)
                    source._set_settings_sources_data(states)

                source_name = source.__name__ if hasattr(source, "__name__") else type(source).__name__
                if isinstance(source, DotEnvSettingsSource) and source.env_file is not None:
                    source_name = f"{type(source).__name__}(env_file={source.env_file})"
                elif isinstance(source, TomlConfigSettingsSource) and source.toml_file_path is not None:
                    source_name = f"{type(source).__name__}(toml_file={source.toml_file_path})"
                source_state = source()
                # hassette logging
                LOGGER.debug("Configuration from %s: %s", source_name, source_state)

                states[source_name] = source_state
                state = self.deep_update(state, source_state, source_name)
                type(self).SETTINGS_SOURCES_DATA = states

            type(self).init_kwargs = {}  # reset after init
            return state

        type(self).init_kwargs = {}  # reset after init

        # no one should mean to do this, but I think returning an empty dict is marginally preferable
        # to an informative error and much better than a confusing error
        return {}

    def _path_to_key(self, path: tuple[str, ...]) -> str:
        return ".".join(path)

    def _prune_below(self, path: tuple[str, ...]) -> None:
        """
        Remove any stale provenance entries at or below `path`.
        Example: if path == ("mqtt","host"), remove "mqtt.host" and "mqtt.host.*"
        """
        prefix = self._path_to_key(path)
        to_delete = []
        for k in type(self).FINAL_SETTINGS_SOURCES:
            if k == prefix or k.startswith(prefix + "."):
                to_delete.append(k)  # noqa: PERF401
        for k in to_delete:
            del type(self).FINAL_SETTINGS_SOURCES[k]

    def deep_update(
        self,
        current_source_state: dict[str, Any],
        new_source_state: dict[str, Any],
        source_name: str,
        parent_path: tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        """
        Incrementally merge `new_source_state` into `current_source_state`,
        recording leaf provenance with LAST-WRITER-WINS semantics.

        - Dicts merge recursively.
        - Lists and scalars replace the previous value entirely.
        - Provenance recorded only at leaves (scalars/lists).
        """
        # Keep a copy so we never mutate the input mapping
        updated: dict[str, Any] = deepcopy(current_source_state)
        parent_path = parent_path or ()

        for k, v in new_source_state.items():
            path = (*parent_path, k)

            # Branch 1: v is a dict → recurse/merge
            if isinstance(v, dict):
                # If we're replacing a non-dict with a dict, clear stale provenance below this key
                if not isinstance(updated.get(k), dict):
                    # Replacing scalar/list with dict → prune prior leaf/subtree provenance
                    self._prune_below(path)
                    # Start fresh subtree
                    updated[k] = {}

                # Recurse into subtree; we expect recursive calls to set leaf provenance
                updated[k] = self.deep_update(updated.get(k, {}), v, source_name, parent_path=path)

            # Branch 2: v is a leaf (scalar or list) → replace & set provenance
            else:
                # Replacing an entire subtree (dict) with a scalar/list? prune children provenance.
                self._prune_below(path)

                updated[k] = v
                leaf_key = self._path_to_key(path)
                if leaf_key in type(self).model_fields and type(self).model_config.get("env_prefix"):
                    # update leaf key with top level namespace
                    # e.g. env_prefix = "hassette__" -> hassette.base_url
                    env_prefix = type(self).model_config.get("env_prefix", "").rstrip("_")
                    leaf_key = f"{env_prefix}.{leaf_key}"
                    # Only record provenance for known fields

                prev_source = type(self).FINAL_SETTINGS_SOURCES.get(leaf_key)
                if prev_source:
                    LOGGER.debug("Setting %s from %s (was %s)", leaf_key, source_name, prev_source)
                type(self).FINAL_SETTINGS_SOURCES[leaf_key] = source_name

        return updated
