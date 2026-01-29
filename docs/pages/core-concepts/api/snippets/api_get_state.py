from typing import cast

from hassette import App, states


class LightApp(App):
    async def on_initialize(self):
        # Get typed state (raises EntityNotFoundError if missing)
        light = cast("states.LightState", await self.api.get_state("light.kitchen"))

        # Access typed attributes
        print(light.attributes.brightness)
