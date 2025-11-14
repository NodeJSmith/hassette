from copy import deepcopy
from logging import getLogger
from pathlib import Path
from typing import Any
from warnings import warn

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings
from pydantic_settings.sources import InitSettingsSource, PathType, TomlConfigSettingsSource

DEFAULT_PATH = Path()

LOGGER = getLogger(__name__)


class HassetteTomlConfigSettingsSource(TomlConfigSettingsSource):
    def __init__(self, settings_cls: type[BaseSettings], toml_file: PathType | None = DEFAULT_PATH):
        self.toml_file_path = toml_file if toml_file != DEFAULT_PATH else settings_cls.model_config.get("toml_file")
        self.toml_data = self._read_files(self.toml_file_path)

        if "hassette" not in self.toml_data:
            # just let the standard class handle it
            super().__init__(settings_cls, self.toml_file_path)
            return

        LOGGER.debug("Merging 'hassette' section from TOML config into top level")
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


class AppManifest(BaseModel):
    """Manifest for a Hassette app."""

    model_config = ConfigDict(
        extra="allow", coerce_numbers_to_str=True, validate_assignment=True, use_attribute_docstrings=True
    )

    app_key: str = Field(default=...)
    """Reflects the key for this app in hassette.toml"""

    enabled: bool = Field(default=True)
    """Whether the app is enabled or not, will default to True if not set"""

    filename: str = Field(default=..., examples=["my_app.py"], validation_alias=AliasChoices("filename", "file_name"))
    """Filename of the app, will be looked for in app_path"""

    class_name: str = Field(
        default=..., examples=["MyApp"], validation_alias=AliasChoices("class_name", "class", "module", "module_name")
    )
    """Class name of the app"""

    display_name: str = Field(default=..., examples=["My App"])
    """Display name of the app, will use class_name if not set"""

    app_dir: Path = Field(..., examples=["./apps"])
    """Path to the app directory, relative to current working directory or absolute"""

    app_config: dict[str, Any] | list[dict[str, Any]] = Field(
        default_factory=dict, validation_alias="config", validate_default=True
    )
    """Instance configuration for the app"""

    auto_loaded: bool = Field(default=False)
    """Whether the app was auto-detected or manually configured"""

    full_path: Path
    """Fully resolved path to the app file"""

    def __repr__(self) -> str:
        return f"<AppManifest {self.display_name} ({self.class_name}) - enabled={self.enabled} file={self.filename}>"

    @model_validator(mode="before")
    @classmethod
    def validate_app_manifest(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Validate the app configuration."""
        required_keys = ["filename", "class_name", "app_dir"]
        missing_keys = [key for key in required_keys if key not in values]
        if missing_keys:
            raise ValueError(f"App configuration is missing required keys: {', '.join(missing_keys)}")

        values["app_dir"] = app_dir = Path(values["app_dir"]).resolve()

        values["display_name"] = values.get("display_name") or values.get("class_name")

        if app_dir.is_file():
            LOGGER.warning("App directory %s is a file, using the parent directory as app_dir", app_dir)
            values["filename"] = app_dir.name
            values["app_dir"] = app_dir.parent

        return values

    @field_validator("app_config", mode="before")
    @classmethod
    def validate_app_config(cls, v: Any, validation_info: ValidationInfo) -> Any:
        """Set instance name if not set in config."""

        if not v:
            return v

        if isinstance(v, dict):
            v = [v]

        class_name = validation_info.data.get("class_name", "UnknownApp")

        for idx, item in enumerate(v):
            if "instance_name" not in item or not item["instance_name"]:
                item["instance_name"] = f"{class_name}.{idx}"

        return v

    def validate_model_extra(self):
        if not self.model_extra:
            return

        keys = list(self.model_extra.keys())
        msg = (
            f"{type(self).__name__} - {self.display_name} - Instance configuration values should be"
            " set under the `config` field:\n"
            f"  {keys}\n"
            "This will ensure proper validation and handling of custom configurations."
        )

        if not self.app_config:
            self.app_config = deepcopy(self.model_extra)
        elif isinstance(self.app_config, dict) and not set(self.app_config).intersection(set(keys)):
            self.app_config.update(deepcopy(self.model_extra))
        else:
            if isinstance(self.app_config, list):
                msg += "\nNote: Unable to merge extra fields into list-based config."
            elif isinstance(self.app_config, dict):
                msg += "\nNote: Unable to merge extra fields into existing config due to intersecting keys."

            msg += "\nExtra fields will be ignored. Please update your configuration."

        warn(msg, stacklevel=5)

    def model_post_init(self, context: Any) -> None:
        self.validate_model_extra()

        # if we don't have app_config then we don't have any apps with config
        # which means we have, at most, one app
        # so we can just set the default instance name
        if not self.app_config:
            self.app_config = [{"instance_name": f"{self.class_name}.0"}]
