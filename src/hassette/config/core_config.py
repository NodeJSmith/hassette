import logging
import os
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Any, ClassVar, Literal

import platformdirs
from packaging.version import Version
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict, TomlConfigSettingsSource

from hassette.logging_ import enable_logging

from .app_manifest import AppManifest
from .hass_config import HassConfig

# Date/Time formats
FORMAT_DATE = "%Y-%m-%d"
FORMAT_TIME = "%H:%M:%S"
FORMAT_DATETIME = f"{FORMAT_DATE} {FORMAT_TIME}"
PACKAGE_KEY = "hassette"
VERSION = Version(version(PACKAGE_KEY))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s:%(lineno)d %(message)s",
    datefmt=FORMAT_DATETIME,
    handlers=[logging.StreamHandler(sys.stdout)],
)

LOGGER = logging.getLogger(__name__)


def default_config_dir() -> Path:
    if env := os.getenv("HASSETTE_CONFIG_DIR"):
        return Path(env)
    docker = Path("/config")
    if docker.exists():
        return docker
    return platformdirs.user_config_path("hassette", version=f"v{VERSION.major}")


def default_data_dir() -> Path:
    if env := os.getenv("HASSETTE_DATA_DIR"):
        return Path(env)
    docker = Path("/data")
    if docker.exists():
        return docker
    return platformdirs.user_data_path("hassette", version=f"v{VERSION.major}")


class HassetteConfig(BaseSettings):
    """Configuration for Hassette."""

    role: ClassVar[str] = "config"

    model_config = SettingsConfigDict(
        env_prefix="hassette__",
        env_file=["/config/.env", ".env"],
        toml_file=["/config/hassette.toml", "hassette.toml"],
        env_ignore_empty=True,
        extra="allow",
        env_nested_delimiter="__",
    )

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", validation_alias=AliasChoices("HASSETTE_LOG_LEVEL", "LOG_LEVEL")
    )

    hass: HassConfig = Field(default_factory=HassConfig)  # pyright: ignore[reportArgumentType]
    apps: dict[str, AppManifest] = Field(
        default_factory=dict, description="Configuration for Hassette apps, keyed by app name."
    )

    data_dir: Path = Field(default_factory=default_data_dir, description="Directory to store Hassette data.")
    config_dir: Path = Field(default_factory=default_config_dir, description="Directory to store Hassette config.")

    websocket_timeout_seconds: int = Field(default=5, description="Timeout for WebSocket requests.")
    run_sync_timeout_seconds: int = Field(default=6, description="Default timeout for synchronous function calls.")

    @field_validator("log_level", mode="before")
    @classmethod
    def log_level_to_uppercase(cls, v: str) -> str:
        return v.upper()

    def model_post_init(self, context: Any):
        self.data_dir.mkdir(parents=True, exist_ok=True)

        enable_logging(self.log_level)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,  # noqa
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        sources = (
            env_settings,
            dotenv_settings,
            TomlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )
        return sources
