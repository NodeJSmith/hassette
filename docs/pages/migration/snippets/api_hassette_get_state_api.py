from hassette import App


class StateGetter(App):
    async def on_initialize(self):
        # Force fresh read from HA (requires await)
        office_light_state = await self.api.get_state("light.office_light_1")
        self.logger.info("office_light_state=%r", office_light_state)
