from typing import cast

from hassette import App, states


class LightApp(App):
    async def on_initialize(self):
        # Raises EntityNotFoundError if missing
        state = await self.api.get_state("light.kitchen")
        light = cast("states.LightState", state)

        # Access typed attributes
        print(light.attributes.brightness)
