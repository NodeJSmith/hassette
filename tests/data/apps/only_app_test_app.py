"""Test app with @only_app decorator for hot reload testing."""

from hassette import App, AppConfig, only_app


class OnlyAppTestConfig(AppConfig):
    """Config for OnlyAppTest."""

    value: str = "default"


@only_app
class OnlyAppTestApp(App[OnlyAppTestConfig]):
    """Test app with @only_app decorator."""

    async def on_initialize(self) -> None:
        self.logger.info("OnlyAppTestApp initialized with value=%s", self.app_config.value)
