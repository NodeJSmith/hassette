from hassette import App, AppConfig, only_app


class MyAppPersistConfig(AppConfig):
    """Config for MyAppPersist."""

    test_value: str = None


@only_app
class MyAppPersist(App[MyAppPersistConfig]):
    """Test app."""

    async def on_initialize(self) -> None:
        self.logger.info("MyAppPersist initialized")
