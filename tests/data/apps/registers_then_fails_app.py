"""Test app that registers a listener and a job, then fails its initialization."""

from hassette import App, AppConfig


class RegistersThenFailsConfig(AppConfig):
    """Configuration for RegistersThenFailsApp."""


class RegistersThenFailsApp(App[RegistersThenFailsConfig]):
    """App whose ``on_initialize()`` registers work and then raises; records whether ``on_shutdown()`` ran."""

    shutdown_called: bool = False

    async def on_initialize(self) -> None:
        await self.bus.on_state_change("light.kitchen", handler=self.on_light, name="kitchen_light")
        await self.scheduler.run_in(self.tick, 3600, name="hourly_tick")
        raise RuntimeError("Intentional init failure after registering work")

    async def on_shutdown(self) -> None:
        self.shutdown_called = True

    async def on_light(self) -> None:
        pass

    async def tick(self) -> None:
        pass
