from hassette import App, AppConfig


class GlobApp(App[AppConfig]):
    async def on_initialize(self):
        # --8<-- [start:glob_patterns]
        # Any light
        await self.bus.on_state_change("light.*", handler=self.on_any_light, name="any_light")

        # Sensors in bedroom
        await self.bus.on_state_change("sensor.bedroom_*", handler=self.on_bedroom_sensor, name="bedroom_sensors")

        # Specific service calls
        await self.bus.on_call_service(
            domain="light",
            service="turn_*",
            handler=self.on_light_service,
            name="light_turn_service",
        )
        # --8<-- [end:glob_patterns]

    async def on_any_light(self):
        pass

    async def on_bedroom_sensor(self):
        pass

    async def on_light_service(self):
        pass
