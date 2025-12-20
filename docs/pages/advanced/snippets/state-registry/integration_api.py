from hassette import App, states


class ApiUsage(App):
    async def usage(self):
        # Automatically converts to LightState
        light_state = await self.api.get_state("light.bedroom", states.LightState)
