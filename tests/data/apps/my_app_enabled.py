from hassette import App, AppConfig


class MyAppEnabledConfig(AppConfig):
    """Config for MyAppEnabled."""


class MyAppEnabled(App[MyAppEnabledConfig]):
    """Test app."""

    async def on_initialize(self) -> None:
        self.logger.info("MyAppEnabled initialized")
