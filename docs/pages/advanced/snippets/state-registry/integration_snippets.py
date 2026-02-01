from typing import cast

from hassette import App, states


class IntegrationApp(App):
    async def api_usage(self):
        # Automatically converts to LightState
        # we use cast to help the type checker understand the type of the returned state
        # since the type checker cannot infer the type of the returned state
        light = cast("states.LightState", await self.api.get_state("light.bedroom"))
        self.logger.info(light)

    async def states_usage(self):
        # Returns typed LightState instance
        self.states.light.get("light.bedroom")
