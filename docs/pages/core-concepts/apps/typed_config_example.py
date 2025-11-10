from pydantic import Field, SecretStr
from pydantic_settings import SettingsConfigDict

from hassette import App, AppConfig


class MyConfig(AppConfig):
    model_config = SettingsConfigDict(env_prefix="MYAPP_")
    entity_id: str = Field(...)
    brightness: int = Field(200, ge=0, le=255)
    required_secret: SecretStr = Field(...)


class MyApp(App[MyConfig]):
    async def on_initialize(self):
        # self.app_config is fully typed here
        await self.api.turn_on(self.app_config.entity_id, brightness=self.app_config.brightness)
