from hassette import App, AppConfig


class MyAppStoppableConfig(AppConfig):
    """Config for MyAppStoppable."""


class MyAppStoppable(App[MyAppStoppableConfig]):
    """Test app."""

    async def on_initialize(self) -> None:
        self.logger.info("MyAppStoppable initialized")
