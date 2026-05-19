from hassette import App, AppConfig


class MyAppNormal2Config(AppConfig):
    """Config for MyAppNormal2."""


class MyAppNormal2(App[MyAppNormal2Config]):
    """Test app."""

    async def on_initialize(self) -> None:
        self.logger.info("MyAppNormal2 initialized")
