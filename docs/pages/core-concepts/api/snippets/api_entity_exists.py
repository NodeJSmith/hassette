from hassette import App


class CheckApp(App):
    async def on_initialize(self):
        if await self.api.entity_exists("light.kitchen"):
            print("Kitchen light is registered")
