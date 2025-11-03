from hassette import App


class RawStateExample(App):
    async def raw_state_example(self):
        raw_state = await self.api.get_state_raw("light.bedroom")
        brightness = raw_state["attributes"].get("brightness")  # Any
        return brightness
