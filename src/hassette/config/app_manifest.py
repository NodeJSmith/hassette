from copy import deepcopy
from logging import getLogger
from pathlib import Path
from typing import Any
from warnings import warn

from pydantic import BaseModel, ConfigDict, Field, model_validator

LOGGER = getLogger(__name__)


class AppManifest(BaseModel):
    """Manifest for a Hassette app."""

    model_config = ConfigDict(extra="allow", coerce_numbers_to_str=True)

    app_key: str = Field(default=...)
    """Reflects the key for this app in hassette.toml"""

    enabled: bool = Field(default=True)
    """Whether the app is enabled or not, will default to True if not set"""

    filename: str = Field(default=..., examples=["my_app.py"])
    """Filename of the app, will be looked for in app_path"""

    class_name: str = Field(default=..., examples=["MyApp"])
    """Class name of the app"""

    display_name: str = Field(default=..., examples=["My App"])
    """Display name of the app, will use class_name if not set"""

    app_dir: Path = Field(..., examples=["./apps"])
    """Path to the app directory, relative to current working directory or absolute"""

    user_config: dict[str, Any] | list[dict[str, Any]] = Field(default_factory=dict, validation_alias="config")
    """User configuration for the app"""

    _full_path: Path | None = None  # Cached full path after first access

    @property
    def full_path(self) -> Path:
        """Get the full path to the app file."""
        if self._full_path is None:
            self._full_path = self._get_full_path()
        return self._full_path

    def _get_full_path(self) -> Path:
        """Get the full path to the app file."""
        if self.app_dir and self.app_dir.exists() and self.app_dir.is_file():
            return self.app_dir

        path = (self.app_dir or Path.cwd()).resolve()
        if not path.exists():
            raise FileNotFoundError(f"App path {path} does not exist")

        if path.is_dir():
            full_path = path / self.filename
            if not full_path.exists():
                raise FileNotFoundError(f"App file {self.filename} does not exist in path {path}")

            return full_path

        raise FileNotFoundError(f"Could not find {self.filename} in directory {path}")

    @model_validator(mode="before")
    @classmethod
    def validate_app_config(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Validate the app configuration."""
        required_keys = ["filename", "class_name", "app_dir"]
        missing_keys = [key for key in required_keys if key not in values]
        if missing_keys:
            raise ValueError(f"App configuration is missing required keys: {', '.join(missing_keys)}")

        values["app_dir"] = app_dir = Path(values["app_dir"]).resolve()

        # if not app_dir.exists():
        #     raise FileNotFoundError(f"App directory {app_dir} does not exist")

        values["display_name"] = values.get("display_name") or values.get("class_name")

        if app_dir.is_file():
            LOGGER.warning("App directory %s is a file, using the parent directory as app_dir", app_dir)
            values["filename"] = app_dir.name
            values["app_dir"] = app_dir.parent

        # if not app_dir.joinpath(values["filename"]).exists():
        #     raise FileNotFoundError(f"App file {values['filename']} does not exist in app_dir {app_dir}")

        return values

    def model_post_init(self, context: Any) -> None:
        if not self.model_extra:
            return super().model_post_init(context)

        keys = list(self.model_extra.keys())
        msg = (
            f"{type(self).__name__} - {self.display_name} - Instance configuration values should be"
            " set under the `config` field:\n"
            f"  {keys}\n"
            "This will ensure proper validation and handling of custom configurations."
        )

        if not self.user_config:
            self.user_config = deepcopy(self.model_extra)
        elif isinstance(self.user_config, dict) and not set(self.user_config).intersection(set(keys)):
            self.user_config.update(deepcopy(self.model_extra))
        else:
            if isinstance(self.user_config, list):
                msg += "\nNote: Unable to merge extra fields into list-based config."
            elif isinstance(self.user_config, dict):
                msg += "\nNote: Unable to merge extra fields into existing config due to intersecting keys."

            msg += "\nExtra fields will be ignored. Please update your configuration."

        warn(msg, stacklevel=5)

        return super().model_post_init(context)
