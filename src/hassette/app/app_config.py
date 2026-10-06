from hassette_wire import LogLevel
from pydantic_settings import BaseSettings, SettingsConfigDict

from hassette.config.defaults import ENV_FILE_LOCATIONS
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
        env_file=ENV_FILE_LOCATIONS,
        env_ignore_empty=True,
        use_attribute_docstrings=True,
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
