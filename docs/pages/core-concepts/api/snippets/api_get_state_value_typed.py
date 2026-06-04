from hassette import App


class MotionApp(App):
    async def on_initialize(self):
        # binary_sensor returns bool at runtime
        motion = await self.api.get_state_value_typed("binary_sensor.front_door")
        self.logger.info("Motion detected: %s", motion)

        # light returns bool at runtime
        light_on = await self.api.get_state_value_typed("light.kitchen")
        self.logger.info("Light on: %s", light_on)

        # sensor returns str — convert manually if numeric
        raw = await self.api.get_state_value_typed("sensor.outdoor_temperature")
        temp = float(raw)
        self.logger.info("Temperature: %.1f", temp)
