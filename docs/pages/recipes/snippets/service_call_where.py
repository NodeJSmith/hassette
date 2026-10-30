from pydantic_settings import SettingsConfigDict

from hassette import App, AppConfig, P
from hassette.events import CallServiceEvent


class LightGroupConfig(AppConfig):
    model_config = SettingsConfigDict(env_prefix="light_group_")

    accent_light: str = "light.living_room_accent"


class LightGroupApp(App[LightGroupConfig]):
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

    async def on_turn_on(self, event: CallServiceEvent) -> None:
        # --8<-- [start:guard]
        service_data = event.payload.data.service_data
        if service_data.get("entity_id") == self.app_config.accent_light:
            return
        # --8<-- [end:guard]
