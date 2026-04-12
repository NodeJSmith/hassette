from hassette import App, states


class StateGetter(App):
    async def on_initialize(self):
        # Access via domain-specific property (no await needed)
        office_light = self.states.light.get("light.office_light_1")

        if office_light:
            self.logger.info("Light state: %s", office_light.value)
            self.logger.info("Brightness: %s", office_light.attributes.brightness)

        # Iterate over all lights
        for entity_id, light in self.states.light:
            self.logger.info("%s: %s", entity_id, light.value)
        # Typed access for any domain
        my_light = self.states[states.LightState].get("light.office_light_1")
