from hassette import App, AppConfig


class RateControlApp(App[AppConfig]):
    async def on_initialize(self):
        # --8<-- [start:rate_control]
        # Debounce: wait for 2s of silence before calling
        await self.bus.on_state_change(
            "binary_sensor.motion",
            handler=self.on_settled,
            debounce=2.0,
            name="motion_debounced",
        )

        # Throttle: call at most once every 5s
        await self.bus.on_state_change(
            "sensor.temperature",
            handler=self.on_temp_log,
            throttle=5.0,
            name="temp_throttled",
        )

        # Once: unsubscribe automatically after first trigger
        await self.bus.on_component_loaded(
            "hue",
            handler=self.on_hue_ready,
            once=True,
            name="hue_ready",
        )
        # --8<-- [end:rate_control]

    async def on_settled(self):
        pass

    async def on_temp_log(self):
        pass

    async def on_hue_ready(self):
        pass
