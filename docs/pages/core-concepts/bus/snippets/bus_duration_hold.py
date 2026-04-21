from hassette import App, AppConfig


class DurationHoldApp(App[AppConfig]):
    async def on_initialize(self):
        # --8<-- [start:duration_hold]
        # Only fire if motion stays on for 30 continuous seconds
        self.bus.on_state_change(
            "binary_sensor.motion",
            handler=self.on_sustained_motion,
            changed_to="on",
            duration=30,
        )

        # Fire once after the door has been open for 5 minutes
        self.bus.on_state_change(
            "binary_sensor.front_door",
            handler=self.on_door_left_open,
            changed_to="on",
            duration=300,
            once=True,
        )

        # Restart-resilient: if the light was already on when the app started
        # and has been on for more than 10 minutes, fire immediately.
        # If it has been on for less, start a timer for the remaining time.
        self.bus.on_state_change(
            "light.porch",
            handler=self.on_porch_on_too_long,
            changed_to="on",
            duration=600,
            immediate=True,
        )
        # --8<-- [end:duration_hold]

    async def on_sustained_motion(self):
        pass

    async def on_door_left_open(self):
        pass

    async def on_porch_on_too_long(self):
        pass
