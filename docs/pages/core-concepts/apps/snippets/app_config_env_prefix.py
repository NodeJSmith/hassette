from pydantic_settings import SettingsConfigDict

from hassette import AppConfig


class MyAppConfig(AppConfig):
    model_config = SettingsConfigDict(env_prefix="MYAPP_")

    api_key: str
