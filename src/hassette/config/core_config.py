import json
import logging
import os
import sys
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path
from typing import Any, ClassVar, Literal

import platformdirs
from dotenv import load_dotenv
from packaging.version import Version
from pydantic import AliasChoices, Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import CliSettingsSource, PydanticBaseSettingsSource, SettingsConfigDict
from yarl import URL

from hassette.logging_ import enable_logging

from .app_manifest import AppManifest
from .sources_helper import HassetteBaseSettings, HassetteTomlConfigSettingsSource

# Date/Time formats
FORMAT_DATE = "%Y-%m-%d"
FORMAT_TIME = "%H:%M:%S"
FORMAT_DATETIME = f"{FORMAT_DATE} {FORMAT_TIME}"
PACKAGE_KEY = "hassette"
VERSION = Version(version(PACKAGE_KEY))
LOG_LEVEL = (
    os.getenv("HASSETTE__LOG_LEVEL") or os.getenv("HASSETTE_LOG_LEVEL") or os.getenv("LOG_LEVEL") or "INFO"
).upper()

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)-8s %(name)s:%(lineno)d %(message)s",
    datefmt=FORMAT_DATETIME,
    handlers=[logging.StreamHandler(sys.stdout)],
)

LOGGER = logging.getLogger(__name__)

# TODO: allow user to specify services/resources to call `set_logger_to_debug` on
# would be cleaner for me as well, so I don't litter the code with `set_logger_to_debug` calls that should probably
# not be there when we cut a new version


def default_config_dir() -> Path:
    if env := os.getenv("HASSETTE__CONFIG_DIR", os.getenv("HASSETTE_CONFIG_DIR")):
        return Path(env)
    docker = Path("/config")
    if docker.exists():
        return docker
    return platformdirs.user_config_path("hassette", version=f"v{VERSION.major}")


def default_data_dir() -> Path:
    if env := os.getenv("HASSETTE__DATA_DIR", os.getenv("HASSETTE_DATA_DIR")):
        return Path(env)
    docker = Path("/data")
    if docker.exists():
        return docker
    return platformdirs.user_data_path("hassette", version=f"v{VERSION.major}")


def default_app_dir() -> Path:
    if env := os.getenv("HASSETTE__APP_DIR", os.getenv("HASSETTE_APP_DIR")):
        return Path(env)
    docker = Path("/apps")
    if docker.exists():
        return docker
    return Path.cwd() / "apps"  # relative to where the program is run


class HassetteConfig(HassetteBaseSettings):
    """Configuration for Hassette."""

    _instance: ClassVar["HassetteConfig"]

    model_config = SettingsConfigDict(
        env_prefix="hassette__",
        env_file=["/config/.env", ".env", "./config/.env"],
        toml_file=["/config/hassette.toml", "hassette.toml", "./config/hassette.toml"],
        env_ignore_empty=True,
        extra="allow",
        env_nested_delimiter="__",
        cli_parse_args=True,
        coerce_numbers_to_str=True,
        validate_by_name=True,
    )

    # General configuration
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(default="INFO")
    """Logging level for Hassette."""

    config_dir: Path = Field(default_factory=default_config_dir)
    """Directory to load/save configuration."""

    data_dir: Path = Field(default_factory=default_data_dir)
    """Directory to store Hassette data."""

    app_dir: Path = Field(default_factory=default_app_dir)
    """Directory to load user apps from."""

    # Home Assistant configuration starts here
    base_url: str = Field(default="http://127.0.0.1:8123")
    """Base URL of the Home Assistant instance"""

    api_port: int = Field(default=8123)
    """API port for Home Assistant, overriden by port in base_url if present"""

    token: SecretStr = Field(
        default=...,
        validation_alias=AliasChoices(
            "token",
            "hassette__token",
            "ha_token",
            "home_assistant_token",
            "t",  # for cli
        ),
        serialization_alias="token",
    )
    """Access token for Home Assistant instance"""

    # App configurations
    apps: dict[str, AppManifest] = Field(default_factory=dict)
    """Configuration for Hassette apps, keyed by app name."""

    # Other configurations
    websocket_timeout_seconds: int = Field(default=5)
    """Timeout for WebSocket requests."""

    run_sync_timeout_seconds: int = Field(default=6)
    """Default timeout for synchronous function calls."""

    run_health_service: bool = Field(default=True)
    """Whether to run the health service for container healthchecks."""

    health_service_port: int | None = Field(default=8126)
    """Port to run the health service on, ignored if run_health_service is False."""

    file_watcher_debounce_milliseconds: int = Field(default=1_600)
    """Debounce time for file watcher events in milliseconds."""

    file_watcher_step_milliseconds: int = Field(default=50)
    """Time to wait for additional file changes before emitting event in milliseconds."""

    watch_files: bool = Field(default=True)
    """Whether to watch files for changes and reload apps automatically."""

    # user config
    secrets: dict[str, SecretStr] = Field(default_factory=dict, examples=["['my_secret','another_secret']"])
    """User provided secrets that can be referenced in the config."""

    @property
    def env_files(self) -> set[Path]:
        """Return a list of environment files that Pydantic will check."""
        return filter_paths_to_unique_existing(self.model_config.get("env_file", []))

    @property
    def toml_files(self) -> set[Path]:
        """Return a list of toml files that Pydantic will check."""
        return filter_paths_to_unique_existing(self.model_config.get("toml_file", []))

    def get_watchable_files(self) -> set[Path]:
        """Return a list of files to watch for changes."""

        files = self.env_files | self.toml_files
        files.add(self.app_dir.resolve())

        # just add everything from here, since we'll filter it to only existing and remove duplicates later
        for app in self.apps.values():
            files.add(app.app_dir)
            files.add(app.full_path)

        files = filter_paths_to_unique_existing(files)

        return files

    @property
    def ws_url(self) -> str:
        """Construct the WebSocket URL for Home Assistant."""
        yurl = URL(self.base_url)
        scheme = yurl.scheme if yurl.scheme else "ws"
        if "http" in scheme:
            scheme = scheme.replace("http", "ws")

        port = yurl.port if yurl.port else self.api_port
        host = yurl.host if yurl.host else self.base_url.split(":")[0]

        return str(URL.build(scheme=scheme, host=host, port=port, path="/api/websocket"))

    @property
    def rest_url(self) -> str:
        """Construct the REST API URL for Home Assistant."""
        yurl = URL(self.base_url)

        port = yurl.port if yurl.port else self.api_port
        scheme = yurl.scheme if yurl.scheme else "http"
        host = yurl.host if yurl.host else self.base_url.split(":")[0]

        return str(URL.build(scheme=scheme, host=host, port=port, path="/api/"))

    @property
    def auth_headers(self) -> dict[str, str]:
        """Return the headers required for authentication."""
        return {"Authorization": f"Bearer {self.token.get_secret_value()}"}

    @property
    def headers(self) -> dict[str, str]:
        """Return the headers for API requests."""
        headers = self.auth_headers.copy()
        headers["Content-Type"] = "application/json"
        return headers

    @property
    def truncated_token(self) -> str:
        """Return a truncated version of the token for display purposes."""
        token_value = self.token.get_secret_value()
        return f"{token_value[:6]}...{token_value[-6:]}"

    @model_validator(mode="after")
    def print_settings_sources(self) -> "HassetteConfig":
        LOGGER.info(
            "Configuration sources: %s",
            json.dumps(type(self).FINAL_SETTINGS_SOURCES, default=str, indent=4, sort_keys=True),
        )
        return self

    @field_validator("secrets", mode="before")
    @classmethod
    def validate_secrets(cls, values: list[str]) -> dict[str, str]:
        """Convert list of secret names to dict of secret values from config sources."""
        if not values:
            return {}

        output = {}

        for k in values:
            if k not in cls.FINAL_SETTINGS_SOURCES:
                if os.getenv(k):
                    LOGGER.info("Filling secret %r from environment variable", k)
                    output[k] = os.getenv(k)
                    cls.FINAL_SETTINGS_SOURCES[f"secrets.{k}"] = "environment variable"
                    continue
                LOGGER.warning("Secret %r not found in any configuration sources, leaving as empty.", k)
                continue

            source_name = cls.FINAL_SETTINGS_SOURCES[k]
            source_data = cls.SETTINGS_SOURCES_DATA.get(source_name, {})
            if k in source_data:
                if source_data[k]:
                    LOGGER.info("Filling empty secret %r from source %r", k, source_name)
                    output[k] = source_data[k]
                    cls.FINAL_SETTINGS_SOURCES[f"secrets.{k}"] = source_name
                    del cls.FINAL_SETTINGS_SOURCES[k]  # delete the non `secrets.` key
                    continue
                LOGGER.warning("Secret %r is empty in source %r, leaving as empty.", k, source_name)

        return output

    @field_validator("apps", mode="before")
    @classmethod
    def validate_apps(cls, values: dict[str, Any], info: ValidationInfo) -> dict[str, Any]:
        """Sets the app_dir in each app manifest if not already set."""
        required_keys = {"filename", "class_name"}
        missing_required = {
            k: v for k, v in values.items() if isinstance(v, dict) and not required_keys.issubset(v.keys())
        }
        if missing_required:
            LOGGER.warning(
                "The following apps are missing required keys (%s) and will be ignored: %s",
                ", ".join(required_keys),
                list(missing_required.keys()),
            )
            for k in missing_required:
                values.pop(k)

        app_dir = info.data.get("app_dir")
        if not app_dir:
            return values
        for k, v in values.items():
            if not isinstance(v, dict):
                continue
            v["app_key"] = k
            if "app_dir" not in v or not v["app_dir"]:
                LOGGER.info("Setting app_dir for app %s to %s", v["filename"], app_dir)
                v["app_dir"] = app_dir
        return values

    @field_validator("log_level", mode="before")
    @classmethod
    def log_level_to_uppercase(cls, v: str) -> str:
        return v.upper()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[HassetteBaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # note: the docs make it sound like the first source returned here is the highest priority
        # but that's not correct (or I'm reading their docs wrong) - the last source to set a value wins
        # so the order here is from lowest priority to highest priority
        #
        # https://docs.pydantic.dev/latest/concepts/pydantic_settings/#changing-priority
        # "The order of the returned callables decides the priority of inputs; first item is the highest priority."

        sources = (
            # we don't error if unknown args are passed, since other things may be passed in CLI
            # that aren't for us (plus it's just very freaking annoying, like damn, not everything's about you)
            CliSettingsSource(settings_cls, cli_ignore_unknown_args=True),
            init_settings,
            HassetteTomlConfigSettingsSource(settings_cls),  # let env, dot_env, and secrets override toml
            env_settings,
            dotenv_settings,  # env file override (if provided) already set in `_settings_build_values`
            file_secret_settings,
        )
        return sources

    def model_post_init(self, context: Any):
        enable_logging(self.log_level)

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)

        envs = set(self.config_dir.rglob("*.env"))
        for env in envs:
            LOGGER.info("Loading environment variables from %s", env)
            load_dotenv(env)

        type(self)._instance = self

    @classmethod
    def get_config(cls) -> "HassetteConfig":
        """Get the global configuration instance."""
        if hasattr(cls, "_instance") and cls._instance is not None:
            return cls._instance

        # TODO: figure out why this is necessary in some cases
        # sometimes the identity of HassetteConfig is different when accessed from different modules
        from hassette.core.core import Hassette

        return Hassette.get_instance().config  # will raise RuntimeError if not initialized yet


def filter_paths_to_unique_existing(value: Sequence[str | Path | None] | str | Path | None | set[Path]) -> set[Path]:
    """Filter the provided paths to only include unique existing paths.

    Args:
        value (list[str]): List of file paths as strings.

    Returns:
        list[Path]: List of existing file paths as Path objects.

    Raises:
        ValueError: If any of the provided paths do not exist.
    """
    value = [value] if isinstance(value, str | Path | None) else value

    paths = set(Path(v).resolve() for v in value if v)
    paths = set(p for p in paths if p.exists())

    return paths
