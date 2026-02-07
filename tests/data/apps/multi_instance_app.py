"""Test app for multiple instance testing."""

from hassette import App, AppConfig


class MultiInstanceConfig(AppConfig):
    """Configuration for MultiInstanceApp."""

    value: str = "default"


class MultiInstanceApp(App[MultiInstanceConfig]):
    """App that can be instantiated multiple times with different configs."""

    async def on_initialize(self) -> None:
        self.logger.info(
            "MultiInstanceApp initialized: instance_name=%s, value=%s",
            self.app_config.instance_name,
            self.app_config.value,
        )
