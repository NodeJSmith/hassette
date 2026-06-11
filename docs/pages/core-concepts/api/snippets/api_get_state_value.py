from hassette import App


class SunApp(App):
    async def on_initialize(self):
        value = await self.api.get_state_value("sun.sun")
        # "above_horizon" or "below_horizon"
        self.logger.info("Sun is: %s", value)
