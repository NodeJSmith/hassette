from hassette import App, AppConfig, P
from hassette.events import CallServiceEvent


class MyApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        await self.bus.on_call_service(
            domain="light",
            service="turn_on",
            handler=self.on_turn_on,
            name="living_room_turn_on",
            # --8<-- [start:where]
            where=P.ServiceDataWhere({"entity_id": "light.living_room_*"})
            # --8<-- [end:where]
        )

    async def on_turn_on(self, event: CallServiceEvent) -> None: ...
