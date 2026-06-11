from hassette import App, AppConfig, D, states


class DoorApp(App[AppConfig]):
    async def on_initialize(self):
        # --8<-- [start:subscribe]
        await self.bus.on_state_change(
            "binary_sensor.front_door",
            handler=self.on_door_change,
            name="front_door",
        )
        # --8<-- [end:subscribe]

    # --8<-- [start:handler]
    async def on_door_change(self, new: D.StateNew[states.BinarySensorState]):
        if new.value is True:
            self.logger.info("Front door opened")
    # --8<-- [end:handler]
