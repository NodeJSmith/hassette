from hassette import App


class LightApp(App):
    async def on_initialize(self):
        # Raw dict
        data = await self.api.get_state_raw("light.kitchen")
        self.logger.info("Raw data: %s", data)
