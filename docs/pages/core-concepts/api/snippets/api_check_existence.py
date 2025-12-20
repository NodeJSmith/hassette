from hassette import App, states


class GhostApp(App):
    async def on_initialize(self):
        if await self.api.get_state_or_none("light.ghost", states.LightState):
            print("It exists!")
