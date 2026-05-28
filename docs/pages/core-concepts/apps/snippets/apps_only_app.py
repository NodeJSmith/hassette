from hassette import App, AppConfig, only_app
from pydantic_settings import SettingsConfigDict


class MyConfig(AppConfig):
    model_config = SettingsConfigDict(env_prefix="my_")


@only_app
class MyApp(App[MyConfig]):
    ...
