from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from hassette.config.defaults import ENV_FILE_LOCATIONS
from hassette.config.helpers import log_level_default_factory
from hassette.types.types import FRAMEWORK_APP_KEY, LOG_LEVEL_TYPE, is_framework_key


class AppConfig(BaseSettings):
    """Base configuration class for applications in the Hassette framework.

    This default class allows all extras, so arbitrary additional configuration data
    can be passed without needing to define a custom subclass, at the cost of type safety.

    Fields can be set on subclasses and extra can be overriden by assigning a new value to `model_config`.
    """

    model_config = SettingsConfigDict(
        extra="allow", arbitrary_types_allowed=True, env_file=ENV_FILE_LOCATIONS, env_ignore_empty=True
    )

    instance_name: str = ""
    """Name for the instance of the app."""

    log_level: LOG_LEVEL_TYPE = Field(default_factory=log_level_default_factory)
    """Log level for the app instance. Defaults to INFO if not provided."""

    app_key: str = ""
    """Configuration-level app key. Reserved: '__hassette__' and '__hassette__.*' prefixes are rejected."""

    @field_validator("app_key")
    @classmethod
    def _reject_hassette_sentinel(cls, v: str) -> str:
        if is_framework_key(v):
            raise ValueError(
                f"'{v}' is a reserved app_key used by the framework internally "
                f"(reserved prefix: '{FRAMEWORK_APP_KEY}' and '{FRAMEWORK_APP_KEY}.'). "
                "Choose a different app_key for your application."
            )
        return v
