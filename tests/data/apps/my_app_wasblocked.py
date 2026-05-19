from hassette import App, AppConfig


class MyAppWasblockedConfig(AppConfig):
    """Config for MyAppWasblocked."""


class MyAppWasblocked(App[MyAppWasblockedConfig]):
    """Test app."""

    async def on_initialize(self) -> None:
        self.logger.info("MyAppWasblocked initialized")
