from hassette import App, AppConfig
from hassette.events import Event


class MyApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        # --8<-- [start:send_event]
        event: Event = Event(topic="lights_synced", payload={"source": self.instance_name})  # pyright: ignore[reportArgumentType]
        await self.send_event("lights_synced", event)
        # --8<-- [end:send_event]
