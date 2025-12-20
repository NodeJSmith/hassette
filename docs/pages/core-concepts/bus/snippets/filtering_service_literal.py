from hassette import App


class LightApp(App):
    async def on_initialize(self):
        # Literal match: brightness MUST be 255
        self.bus.on_call_service(
            domain="light",
            service="turn_on",
            where={"entity_id": "light.living_room", "brightness": 255},
            handler=self.on_bright_living_room,
        )

    async def on_bright_living_room(self, event):
        pass
