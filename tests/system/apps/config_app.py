"""Config-driven app fixture for system tests."""

from pydantic_settings import SettingsConfigDict

from hassette import App, AppConfig


class ConfigAppConfig(AppConfig):
    """Configuration for ConfigApp."""

    model_config = SettingsConfigDict(env_prefix="config_app_")

    greeting: str = "hello"


class ConfigApp(App[ConfigAppConfig]):
    """App that reads its greeting from config — used to verify config injection."""

    async def on_initialize(self) -> None:
        self._greeting = self.app_config.greeting
