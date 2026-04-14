from hassette import App, AppConfig


class RateControlApp(App[AppConfig]):
    async def on_initialize(self):
        # --8<-- [start:rate_control]
        # Debounce: wait for 2s of silence before calling
        self.bus.on_state_change(
            "binary_sensor.motion",
            handler=self.on_settled,
            debounce=2.0,
        )

        # Throttle: call at most once every 5s
        self.bus.on_state_change(
            "sensor.temperature",
            handler=self.on_temp_log,
            throttle=5.0,
        )

        # Once: unsubscribe automatically after first trigger
        self.bus.on_component_loaded(
            "hue",
            handler=self.on_hue_ready,
            once=True,
        )
        # --8<-- [end:rate_control]

    async def on_settled(self):
        pass

    async def on_temp_log(self):
        pass

    async def on_hue_ready(self):
        pass
