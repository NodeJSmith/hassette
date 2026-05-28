from dataclasses import dataclass

from hassette import App, AppConfig
from hassette.events import Event, HassettePayload


@dataclass(frozen=True, slots=True)
class LightsSyncedData:
    source: str


class MyApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        # --8<-- [start:send_event]
        payload = HassettePayload(event_type="lights_synced", data=LightsSyncedData(source=self.instance_name))
        await self.send_event("lights_synced", Event(topic="lights_synced", payload=payload))
        # --8<-- [end:send_event]
