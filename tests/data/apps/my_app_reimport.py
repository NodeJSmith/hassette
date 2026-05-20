from hassette import App, AppConfig


class MyAppReimportConfig(AppConfig):
    """Config for MyAppReimport."""


class MyAppReimport(App[MyAppReimportConfig]):
    """Test app."""

    async def on_initialize(self) -> None:
        self.logger.info("MyAppReimport initialized")
