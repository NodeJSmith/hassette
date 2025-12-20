from hassette import App


class IteratorApp(App):
    async def on_initialize(self):
        # Find all low battery sensors
        for entity_id, sensor in self.states.sensor:
            if sensor.attributes.battery_level and sensor.attributes.battery_level < 20:
                self.logger.warning("Low battery: %s", entity_id)
