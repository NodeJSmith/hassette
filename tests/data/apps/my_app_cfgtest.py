from hassette import App, AppConfig


class MyAppCfgtestConfig(AppConfig):
    """Config for MyAppCfgtest."""

    test_value: str = None


class MyAppCfgtest(App[MyAppCfgtestConfig]):
    """Test app."""

    async def on_initialize(self) -> None:
        self.logger.info("MyAppCfgtest initialized")
