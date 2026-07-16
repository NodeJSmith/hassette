from hassette import App


class IteratorApp(App):
    async def on_initialize(self):
        # Find all low battery sensors
        for entity_id, sensor in self.states.sensor.items():
            # battery_level is not declared on the typed attributes model,
            # so read it via .extra(), which returns None when absent
            battery = sensor.attributes.extra("battery_level")
            if battery is not None and battery < 20:
                self.logger.warning("Low battery: %s", entity_id)
