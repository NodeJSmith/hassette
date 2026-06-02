from hassette import App, AppConfig


class PresenceApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        # --8<-- [start:duration]
        # Fire only after a door has stayed open for 5 minutes
        await self.bus.on_state_change(
            "binary_sensor.front_door",
            handler=self.on_door_left_open,
            changed_to="on",
            duration=300,
            once=True,
            name="front_door_open_long",
        )
        # --8<-- [end:duration]

    async def on_door_left_open(self) -> None:
        self.logger.warning("Front door has been open for 5 minutes")
