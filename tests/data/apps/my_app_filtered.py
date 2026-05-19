from hassette import App, AppConfig


class MyAppFilteredConfig(AppConfig):
    """Config for MyAppFiltered."""


class MyAppFiltered(App[MyAppFilteredConfig]):
    """Test app."""

    async def on_initialize(self) -> None:
        self.logger.info("MyAppFiltered initialized")
