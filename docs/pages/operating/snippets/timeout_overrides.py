from hassette import App, AppConfig
from hassette.events import RawStateChangeEvent


class TimeoutOverrideApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        # --8<-- [start:overrides]
        # use a tighter timeout for this handler
        await self.bus.on_state_change(
            "sensor.outdoor_temperature",
            handler=self.on_temp_change,
            name="my_app.temp",
            timeout=30,
        )

        # disable the timeout entirely for a long-running job
        await self.scheduler.run_every(
            self.rebuild_cache,
            minutes=15,
            name="rebuild_cache",
            timeout_disabled=True,
        )
        # --8<-- [end:overrides]

    async def on_temp_change(self, event: RawStateChangeEvent) -> None:
        pass

    async def rebuild_cache(self) -> None:
        pass
