from hassette import App, states


class LightApp(App):
    async def on_initialize(self):
        # Get typed state (raises EntityNotFoundError if missing)
        light = await self.api.get_state("light.kitchen", states.LightState)

        # Access typed attributes
        print(light.attributes.brightness)
