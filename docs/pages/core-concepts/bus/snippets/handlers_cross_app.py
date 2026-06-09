from dataclasses import dataclass

from hassette import App, AppConfig, D, states


# --8<-- [start:sender]
@dataclass(frozen=True)
class LightsSyncedData:
    source: str


class SenderApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        await self.bus.on_state_change(
            "light.kitchen",
            handler=self.on_kitchen_change,
            name="kitchen_light",
        )

    async def on_kitchen_change(
        self,
        state: D.StateNew[states.LightState],
    ) -> None:
        await self.bus.emit(
            "lights_synced",
            LightsSyncedData(source=self.instance_name),
        )
# --8<-- [end:sender]


# --8<-- [start:receiver]
class ReceiverApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        await self.bus.on(
            topic="lights_synced",
            handler=self.on_lights_synced,
            name="lights_synced_log",
        )

    async def on_lights_synced(
        self,
        data: D.EventData[LightsSyncedData],
    ) -> None:
        self.logger.info("Synced by %s", data.source)
# --8<-- [end:receiver]
