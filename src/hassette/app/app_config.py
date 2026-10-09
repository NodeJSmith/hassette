import os
from contextlib import suppress
from pathlib import Path

from hassette_wire import LogLevel
from pydantic_settings import BaseSettings, DotEnvSettingsSource, PydanticBaseSettingsSource, SettingsConfigDict

from hassette import context
from hassette.config.locations import resolve_locations
from hassette.exceptions import HassetteNotInitializedError
from hassette.types.enums import BlockingIOBehavior, ForgottenAwaitBehavior


class AppConfig(BaseSettings):
    """Base configuration class for applications in the Hassette framework.

    This default class allows all extras, so arbitrary additional configuration data
    can be passed without needing to define a custom subclass, at the cost of type safety.

    Fields can be set on subclasses and extra can be overridden by assigning a new value to `model_config`.
    """

    model_config = SettingsConfigDict(
        extra="allow",
        arbitrary_types_allowed=True,
        env_ignore_empty=True,
        use_attribute_docstrings=True,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Read the same ``.env`` files as the running Hassette config, unless the subclass pins ``env_file``."""
        if cls.model_config.get("env_file") is not None:
            return (init_settings, env_settings, dotenv_settings, file_secret_settings)
        return (
            init_settings,
            env_settings,
            DotEnvSettingsSource(settings_cls, env_file=list(hassette_env_files())),
            file_secret_settings,
        )

    instance_name: str = ""
    """Name for the instance of the app."""

    log_level: LogLevel | None = None
    """Log level for the app instance.

    When ``None`` (default), the global ``logging.apps`` level from ``hassette.toml`` is used."""

    forgotten_await_behavior: ForgottenAwaitBehavior | None = None
    """Per-app control for forgotten-await detection behavior.

    When ``None`` (default), the global ``HassetteConfig.forgotten_await_behavior`` is used,
    which itself defaults to ``"warn"``.  Set to ``"ignore"`` to suppress warnings for this app,
    or ``"error"`` to treat forgotten awaits as errors (escalated by ``filterwarnings("error")``)."""

    blocking_io_behavior: BlockingIOBehavior | None = None
    """Per-app control for blocking-IO detection behavior.

    When ``None`` (default), the global ``HassetteConfig.blocking_io.behavior`` is used,
    which itself defaults to ``"warn"``.  Set to ``"ignore"`` to suppress detection for this app,
    or ``"error"`` to escalate via ``filterwarnings("error")``."""


def hassette_env_files() -> tuple[Path, ...]:
    """The ``.env`` files of the running Hassette config, or the default search outside of one."""
    with suppress(HassetteNotInitializedError):
        return context.get_hassette_config().locations.env_files
    return resolve_locations(os.environ).env_files
