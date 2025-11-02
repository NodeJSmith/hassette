from hassette import App, StateChangeEvent


class PassingArgumentsExample(App):
    async def on_initialize(self):
        # Pass extra context to the handler
        self.bus.on_state_change(
            "light.bedroom", handler=self.on_light_change, args=("bedroom",), kwargs={"room_type": "sleeping"}
        )

    async def on_light_change(self, event: StateChangeEvent, room_name: str, *, room_type: str):
        self.logger.info("Light in %s (%s) changed", room_name, room_type)
