from hassette import App


class EmptyHouseDoorApp(App):
    async def on_initialize(self):
        # Runs for each door event, reading presence from the state cache
        await self.bus.on_state_change(
            "binary_sensor.front_door",
            handler=self.on_door,
            changed_to="on",
            where=lambda _: self.states.nobody_home(),
            name="door_when_empty",
        )

    async def on_door(self):
        self.logger.warning("Front door opened with nobody home")
