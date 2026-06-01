from hassette import App, AppConfig


class RateControlApp(App[AppConfig]):
    async def on_initialize(self):
        # --8<-- [start:rate_control]
        # --8<-- [start:debounce]
        await self.bus.on_state_change(
            "binary_sensor.motion",
            handler=self.on_settled,
            debounce=2.0,
            name="motion_debounced",
        )
        # --8<-- [end:debounce]

        # --8<-- [start:throttle]
        await self.bus.on_state_change(
            "sensor.temperature",
            handler=self.on_temp_log,
            throttle=5.0,
            name="temp_throttled",
        )
        # --8<-- [end:throttle]

        # --8<-- [start:once]
        await self.bus.on_state_change(
            "binary_sensor.front_door",
            handler=self.on_door_opened,
            changed_to="on",
            once=True,
            name="door_opened_once",
        )
        # --8<-- [end:once]
        # --8<-- [end:rate_control]

    async def on_settled(self):
        pass

    async def on_temp_log(self):
        pass

    async def on_door_opened(self):
        pass
