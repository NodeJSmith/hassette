from hassette import App


class LowLevelExample(App):
    async def low_level_example(self):
        response = await self.api.rest_request("GET", "config")
        cfg = await response.json()
        await self.api.ws_send_json(type="ping")
        return cfg
