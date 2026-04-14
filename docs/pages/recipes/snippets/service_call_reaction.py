from pydantic_settings import SettingsConfigDict

from hassette import App, AppConfig, P
from hassette.events import CallServiceEvent


class LightGroupConfig(AppConfig):
    model_config = SettingsConfigDict(env_prefix="light_group_")

    primary_light: str = "light.living_room_main"
    accent_light: str = "light.living_room_accent"


class LightGroupApp(App[LightGroupConfig]):
    """Mirror accent light whenever the primary light is turned on."""

    async def on_initialize(self) -> None:
        self.bus.on_call_service(
            domain="light",
            service="turn_on",
            where=P.ServiceDataWhere({"entity_id": self.app_config.primary_light}),
            handler=self.on_primary_turned_on,
        )

    async def on_primary_turned_on(self, event: CallServiceEvent) -> None:
        service_data = event.payload.data.service_data
        brightness = service_data.get("brightness")
        color_temp = service_data.get("color_temp")

        self.logger.info(
            "Primary light turned on (brightness=%s, color_temp=%s) — syncing accent",
            brightness,
            color_temp,
        )

        call_data: dict[str, object] = {"entity_id": self.app_config.accent_light}
        if brightness is not None:
            call_data["brightness"] = brightness
        if color_temp is not None:
            call_data["color_temp"] = color_temp

        await self.api.call_service("light", "turn_on", service_data=call_data)
