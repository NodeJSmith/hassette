from hassette import App, states


class MyApp(App):
    async def on_initialize(self):
        # PREFERRED: Use local state cache (no await, no API call)
        # This is most similar to AppDaemon's behavior
        light = self.states.light.get("light.kitchen")
        if light:
            brightness = light.attributes.brightness  # Type-safe access
            value = light.value  # State value as string

        # Iterate over all lights in cache
        for entity_id, light in self.states.light:
            self.logger.info("%s: %s", entity_id, light.value)

        # Typed access for any domain
        my_light = self.states[states.LightState].get("light.kitchen")

        # ALTERNATIVE: Force fresh read from Home Assistant API
        fresh_light = await self.api.get_state("light.kitchen")
        brightness = fresh_light.attributes.brightness  # pyright: ignore[reportAttributeAccessIssue]

        # Or get just the value
        value = await self.api.get_state_value("light.kitchen")  # Returns string
