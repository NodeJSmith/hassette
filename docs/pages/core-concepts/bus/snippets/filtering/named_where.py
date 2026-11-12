from hassette import App, AppConfig
from hassette.events import RawStateChangeEvent


# --8<-- [start:named_where]
def is_dark(event: RawStateChangeEvent) -> bool:
    new = event.payload.data.new_state
    if new is None:
        return False
    lux = new["attributes"].get("illuminance")
    if lux is None:
        return False
    return lux < 10


class HallLights(App[AppConfig]):
    async def on_initialize(self) -> None:
        await self.bus.on_state_change(
            "binary_sensor.hall_motion",
            changed_to="on",
            where=is_dark,
            handler=self.on_motion,
            name="hall_motion",
        )
        # --8<-- [end:named_where]

    async def on_motion(self) -> None: ...
