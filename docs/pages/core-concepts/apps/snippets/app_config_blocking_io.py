from hassette import App, AppConfig, BlockingIOBehavior
from pydantic_settings import SettingsConfigDict


class MyAppConfig(AppConfig):
    model_config = SettingsConfigDict(env_prefix="my_")
    blocking_io_behavior: BlockingIOBehavior | None = BlockingIOBehavior.IGNORE


class MyApp(App[MyAppConfig]):
    async def on_initialize(self) -> None:
        pass
