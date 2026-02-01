from hassette import App, D, states


class LightMonitor(App):
    async def on_initialize(self):
        self.bus.on_state_change(
            "light.bedroom",
            handler=self.on_light_change,
        )

    async def on_light_change(self, new_state: D.StateNew[states.LightState], entity_id: D.EntityId):
        brightness = new_state.attributes.brightness
        self.logger.info("%s brightness: %s", entity_id, brightness)
