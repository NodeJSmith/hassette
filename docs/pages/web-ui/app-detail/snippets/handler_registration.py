from hassette import App, AppConfig
from hassette.bus.event import RawStateChangeEvent


class MyApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        # --8<-- [start:register]
        self.bus.on_state_change("light.kitchen", handler=self.on_light_change)
        # --8<-- [end:register]

    async def on_light_change(self, event: RawStateChangeEvent) -> None: ...
