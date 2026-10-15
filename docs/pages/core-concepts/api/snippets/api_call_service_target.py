from hassette import App


class PorchLightApp(App):
    async def on_initialize(self):
        # --8<-- [start:target]
        await self.api.call_service(
            "light",
            "turn_on",
            target={"entity_id": "light.porch"},
            brightness=200,
        )
        # --8<-- [end:target]

        # --8<-- [start:data]
        await self.api.call_service(
            "light",
            "turn_on",
            entity_id="light.porch",
            brightness=200,
        )
        # --8<-- [end:data]
