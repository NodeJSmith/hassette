from hassette import App


class PassingArgumentsExample(App):
    async def on_initialize(self):
        # Pass extra context to the handler
        self.bus.on_state_change("light.bedroom", handler=self.on_light_change, kwargs={"room_name": "Gustav's Room"})

    async def on_light_change(self, room_name: str):
        # event argument omitted since we don't need it
        self.logger.info("Light in %s changed", room_name)
