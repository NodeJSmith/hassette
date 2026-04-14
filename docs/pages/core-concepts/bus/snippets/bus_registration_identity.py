from hassette import App, AppConfig


class NamedSubscriptionApp(App[AppConfig]):
    async def on_initialize(self):
        # --8<-- [start:registration_identity]
        self.bus.on_state_change(
            "binary_sensor.motion",
            handler=self.on_motion,
            name="motion_sensor_main",
        )

        self.bus.on_state_change(
            "binary_sensor.motion",
            handler=self.on_motion_log,
            name="motion_sensor_log",
        )
        # --8<-- [end:registration_identity]

    async def on_motion(self):
        pass

    async def on_motion_log(self):
        pass
