from hassette import AppConfig
from pydantic_settings import SettingsConfigDict


class MyAppConfig(AppConfig):
    model_config = SettingsConfigDict(env_prefix="MYAPP_")

    api_key: str
