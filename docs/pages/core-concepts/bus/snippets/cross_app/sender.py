from hassette import App, AppConfig, D, states

from .shared import LightsSyncedData


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
