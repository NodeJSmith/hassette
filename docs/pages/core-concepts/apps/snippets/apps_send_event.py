from hassette import App, AppConfig
from hassette.bus.event import Event


class MyApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        # --8<-- [start:send_event]
        await self.send_event("lights_synced", Event(data={"source": self.instance_name}))
        # --8<-- [end:send_event]
