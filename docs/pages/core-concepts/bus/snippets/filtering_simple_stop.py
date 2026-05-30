from hassette import App


class MotionApp(App):
    async def on_initialize(self):
        # Handle when motion stops
        await self.bus.on_state_change(
            "binary_sensor.front_door",
            handler=self.on_motion_stop,
            changed_from="on",
            name="front_door_motion_stop",
        )

    async def on_motion_stop(self, event):
        pass
