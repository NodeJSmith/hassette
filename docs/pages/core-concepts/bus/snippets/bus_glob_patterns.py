from hassette import App, AppConfig


class GlobApp(App[AppConfig]):
    async def on_initialize(self):
        # --8<-- [start:glob_patterns]
        # Any light
        self.bus.on_state_change("light.*", handler=self.on_any_light)

        # Sensors in bedroom
        self.bus.on_state_change("sensor.bedroom_*", handler=self.on_bedroom_sensor)

        # Specific service calls
        self.bus.on_call_service(
            domain="light",
            service="turn_*",
            handler=self.on_light_service,
        )
        # --8<-- [end:glob_patterns]

    async def on_any_light(self):
        pass

    async def on_bedroom_sensor(self):
        pass

    async def on_light_service(self):
        pass
