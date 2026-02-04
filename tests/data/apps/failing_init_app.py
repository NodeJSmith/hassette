"""Test app that fails during initialization for exception handling testing."""

from hassette import App, AppConfig


class FailingInitConfig(AppConfig):
    """Configuration for FailingInitApp."""

    error_message: str = "Intentional init failure for testing"


class FailingInitApp(App[FailingInitConfig]):
    """App that raises an exception during initialization."""

    async def on_initialize(self) -> None:
        self.logger.info("FailingInitApp about to raise exception")
        raise RuntimeError(self.app_config.error_message)
