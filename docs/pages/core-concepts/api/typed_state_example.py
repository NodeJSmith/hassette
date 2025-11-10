from hassette import App, states


class TypedStateExample(App):
    async def typed_state_example(self):
        light_state = await self.api.get_state("light.bedroom", states.LightState)
        brightness = light_state.attributes.brightness  # float | None
        return brightness
