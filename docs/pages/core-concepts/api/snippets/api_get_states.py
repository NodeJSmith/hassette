from hassette import App


class StateApp(App):
    async def on_initialize(self):
        all_states = await self.api.get_states()
        lights = [s for s in all_states if s.domain == "light"]
        self.logger.info("Found %d lights", len(lights))
