from hassette import App, AppConfig, only_app


class MyAppOnlyremoveConfig(AppConfig):
    """Config for MyAppOnlyremove."""


@only_app
class MyAppOnlyremove(App[MyAppOnlyremoveConfig]):
    """Test app."""

    async def on_initialize(self) -> None:
        self.logger.info("MyAppOnlyremove initialized")
