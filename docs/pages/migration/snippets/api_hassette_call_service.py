from hassette import App


class MyApp(App):
    async def my_callback(self):
        await self.api.call_service(
            "light",
            "turn_on",
            target={"entity_id": "light.kitchen"},
            brightness=200,
        )
        # Or use the helper
        await self.api.turn_on("light.kitchen", brightness=200)
