"""Test app with slow initialization for timeout testing."""

import asyncio

from hassette import App, AppConfig


class SlowInitConfig(AppConfig):
    """Configuration for SlowInitApp."""

    delay_seconds: float = 5.0


class SlowInitApp(App[SlowInitConfig]):
    """App that sleeps during initialization to test timeout handling."""

    async def on_initialize(self) -> None:
        self.logger.info("SlowInitApp starting slow initialization (delay=%s)", self.app_config.delay_seconds)
        await asyncio.sleep(self.app_config.delay_seconds)
        self.logger.info("SlowInitApp finished initialization")
