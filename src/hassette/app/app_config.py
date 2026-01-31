from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from hassette.config.defaults import ENV_FILE_LOCATIONS
from hassette.config.helpers import log_level_default_factory
from hassette.types.types import LOG_LEVEL_TYPE


class AppConfig(BaseSettings):
    """Base configuration class for applications in the Hassette framework.

    This default class does not define any fields, allowing anyone who prefers to not use
    this functionality to ignore it. It also allows all extras, so arbitrary additional
    configuration data can be passed without needing to define a custom subclass.

    Fields can be set on subclasses and extra can be overriden by assigning a new value to `model_config`."""

    model_config = SettingsConfigDict(
        extra="allow", arbitrary_types_allowed=True, env_file=ENV_FILE_LOCATIONS, env_ignore_empty=True
    )

    instance_name: str = ""
    """Name for the instance of the app."""

    log_level: LOG_LEVEL_TYPE = Field(default_factory=log_level_default_factory)
    """Log level for the app instance. Defaults to Hassette default if not provided."""
