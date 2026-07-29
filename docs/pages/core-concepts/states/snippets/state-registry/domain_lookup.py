from hassette import App


class LightApp(App):
    async def on_initialize(self):
        # Get class for a domain
        light_state_class = self.state_registry.resolve(domain="light")
        assert light_state_class is not None
        self.logger.info("Light states use %s", light_state_class.__name__)
