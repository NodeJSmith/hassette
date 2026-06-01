from dataclasses import dataclass

from hassette import App, AppConfig, D
from hassette.models import states


@dataclass(frozen=True, slots=True)
class LightsSyncedData:
    source: str


# --8<-- [start:sender]
class LightManagerApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        await self.bus.on_state_change(
            "light.kitchen",
            handler=self.on_kitchen_change,
            name="kitchen_sync",
        )

    async def on_kitchen_change(self, state: D.StateNew[states.LightState]) -> None:
        await self.bus.emit("lights_synced", LightsSyncedData(source=self.instance_name))
# --8<-- [end:sender]


# --8<-- [start:receiver]
class LoggerApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        await self.bus.on(topic="lights_synced", handler=self.on_lights_synced, name="lights_synced_log")

    async def on_lights_synced(self, data: D.EventData[LightsSyncedData]) -> None:
        # Guard against self-delivery if this app also emits on the same topic
        if data.source == self.instance_name:
            return
        self.logger.info("Lights synced by %s", data.source)
# --8<-- [end:receiver]
