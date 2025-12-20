from hassette import App, dependencies as D, states


class IntegrationApp(App):
    async def di_usage(self):
        # DI annotation uses StateRegistry internally
        pass

    async def api_usage(self):
        # Automatically converts to LightState
        light_state = await self.api.get_state("light.bedroom", states.LightState)

    async def states_usage(self):
        # Returns typed LightState instance
        light = self.states.light.get("light.bedroom")
