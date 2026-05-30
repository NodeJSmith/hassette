from hassette import App


class MotionApp(App):
    async def on_initialize(self):
        # Handle when motion starts
        await self.bus.on_state_change(
            "binary_sensor.front_door",
            handler=self.on_motion,
            changed_to="on",
            name="front_door_motion",
        )

    async def on_motion(self, event):
        pass
