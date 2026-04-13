from hassette import App


class IteratorApp(App):
    async def on_initialize(self):
        # Find all low battery sensors
        for entity_id, sensor in self.states.sensor:
            # sensor.attributes is a plain Pydantic model; unrecognised fields are
            # not declared on the class, so access them via hasattr/getattr.
            if not hasattr(sensor.attributes, "battery_level"):
                continue
            if sensor.attributes.battery_level < 20:  # pyright: ignore[reportAttributeAccessIssue]
                self.logger.warning("Low battery: %s", entity_id)
