from hassette import App


class StateApp(App):
    async def on_initialize(self):
        raw_states = await self.api.get_states_raw()
        for s in raw_states:
            self.logger.info("%s: %s", s["entity_id"], s["state"])
