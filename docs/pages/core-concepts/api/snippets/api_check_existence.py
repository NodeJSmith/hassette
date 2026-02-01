from hassette import App


class GhostApp(App):
    async def on_initialize(self):
        if await self.api.get_state_or_none("light.ghost"):
            print("It exists!")
