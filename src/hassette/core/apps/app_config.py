from typing import TypeVar

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """Base configuration class for applications in the Hassette framework.

    This default class does not define any fields, allowing anyone who prefers to not use
    this functionality to ignore it. It also allows all extras, so that no checking/validation
    is done on incoming configuration data.

    Fields can be set on subclasses and extra can be overriden by assigning a new value to `model_config`."""

    model_config = SettingsConfigDict(extra="allow")


AppConfigT = TypeVar("AppConfigT", bound=AppConfig)
"""Type variable for app configuration classes."""


DEFAULT_CONFIG = AppConfig()
"""Default configuration for apps."""
