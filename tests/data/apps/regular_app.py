"""Regular test app without decorator for hot reload testing."""

from hassette import App, AppConfig


class RegularAppConfig(AppConfig):
    """Config for RegularApp."""

    pass


class RegularApp(App[RegularAppConfig]):
    """Regular test app without decorator."""

    async def on_initialize(self) -> None:
        self.logger.info("RegularApp initialized")
