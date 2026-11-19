"""Test app that declares an entity and writes to it from its shutdown hook, for commit-failure testing."""

from hassette import App, AppConfig, IntegrationSensor


class IntegrationCommitConfig(AppConfig):
    """Configuration for IntegrationCommitApp."""


class IntegrationCommitApp(App[IntegrationCommitConfig]):
    """Declares a sensor in ``on_initialize`` and records what ``set()`` does in ``on_shutdown``."""

    temp: IntegrationSensor

    async def on_initialize(self) -> None:
        self.shutdown_hook_ran = False
        self.shutdown_set_error: Exception | None = None
        self.temp = await self.integration.add_sensor("temp", name="Temp", unit="°C", device_class="temperature")
        await self.temp.set(21.5)

    async def on_shutdown(self) -> None:
        self.shutdown_hook_ran = True
        try:
            await self.temp.set(30.0)
        except Exception as exc:
            self.shutdown_set_error = exc
