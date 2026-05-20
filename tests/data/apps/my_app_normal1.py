from hassette import App, AppConfig


class MyAppNormal1Config(AppConfig):
    """Config for MyAppNormal1."""


class MyAppNormal1(App[MyAppNormal1Config]):
    """Test app."""

    async def on_initialize(self) -> None:
        self.logger.info("MyAppNormal1 initialized")
