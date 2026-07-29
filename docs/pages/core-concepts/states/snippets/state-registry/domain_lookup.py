from hassette import App


class LightApp(App):
    async def on_initialize(self):
        # Get class for a domain
        state_class = self.state_registry.resolve(domain="light")
        # Returns: LightState
