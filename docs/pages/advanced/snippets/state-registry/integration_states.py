from hassette import App


class StatesUsage(App):
    async def usage(self):
        # Returns typed LightState instance
        light = self.states.light.get("light.bedroom")
        self.logger.info(light)
