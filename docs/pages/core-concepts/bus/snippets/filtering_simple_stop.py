from hassette import App


class MotionApp(App):
    async def on_initialize(self):
        # Handle when motion stops
        self.bus.on_state_change(
            "binary_sensor.front_door",
            handler=self.on_motion_stop,
            changed_from="on",
        )

    async def on_motion_stop(self, event):
        pass
