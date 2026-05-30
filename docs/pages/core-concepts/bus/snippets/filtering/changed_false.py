from hassette import App, AppConfig
from hassette.events import RawStateChangeEvent


class MyApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        # --8<-- [start:changed_false]
        # Fire even when only attributes change, not the main state value
        await self.bus.on_state_change("light.office", handler=self.on_light_change, changed=False, name="office_light_attrs")
        # --8<-- [end:changed_false]

    async def on_light_change(self, event: RawStateChangeEvent) -> None: ...
