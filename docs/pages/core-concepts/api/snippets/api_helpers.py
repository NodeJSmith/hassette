from hassette import App


class HelperApp(App):
    async def on_initialize(self):
        # Turn on with attributes
        await self.api.turn_on("light.kitchen", brightness=255, color_name="blue")

        # Turn off
        await self.api.turn_off("switch.fan")
