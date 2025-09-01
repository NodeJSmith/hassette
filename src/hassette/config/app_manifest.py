from pathlib import Path
from typing import Any, ClassVar
from warnings import warn

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# note to future self: do not rename app_path to path, as it causes Pydantic to set it to $PATH


class AppManifest(BaseSettings):
    role: ClassVar[str] = "config"

    model_config = SettingsConfigDict(extra="allow")

    enabled: bool
    filename: str | Path
    class_name: str
    display_name: str
    app_path: Path | None = Field(None, description="Path to the app directory, relative to current working directory")

    user_config: dict[str, Any] | list[dict[str, Any]] = Field(
        default_factory=dict, description="User configuration for the app", validation_alias="config"
    )

    def get_full_path(self) -> Path:
        """Get the full path to the app file."""
        if self.app_path and self.app_path.exists() and self.app_path.is_file():
            return self.app_path

        path = (self.app_path or Path.cwd()).resolve()
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

        if isinstance(values.get("filename"), str):
            values["filename"] = Path(values["filename"])

        if isinstance(values.get("app_path"), str):
            values["app_path"] = app_path = Path(values["app_path"]).resolve()
            if not app_path.exists():
                raise FileNotFoundError(f"App path {app_path} does not exist")
            if app_path.exists() and app_path.is_file():
                values["filename"] = app_path.name

        if "display_name" not in values or not values["display_name"]:
            if values.get("filename"):
                values["display_name"] = Path(values["filename"]).stem

        return values

    def model_post_init(self, context: Any) -> None:
        if self.model_extra:
            keys = list(self.model_extra.keys())
            warn(
                f"{type(self).__name__} - {self.display_name} - Instance configuration values should be"
                " set under the `config` field:\n"
                f"  {keys}\n"
                "This will ensure proper validation and handling of custom configurations.",
                stacklevel=2,
            )

        return super().model_post_init(context)
