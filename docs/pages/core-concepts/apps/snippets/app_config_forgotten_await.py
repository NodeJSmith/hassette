from hassette import App, AppConfig, ForgottenAwaitBehavior
from pydantic_settings import SettingsConfigDict


class MyAppConfig(AppConfig):
    model_config = SettingsConfigDict(env_prefix="my_")
    forgotten_await_behavior: ForgottenAwaitBehavior | None = ForgottenAwaitBehavior.ERROR


class MyApp(App[MyAppConfig]):
    async def on_initialize(self) -> None:
        pass
