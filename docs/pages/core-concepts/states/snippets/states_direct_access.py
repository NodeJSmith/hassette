from hassette import App


class DirectAccessApp(App):
    async def on_initialize(self):
        # Access any entity by full entity ID
        light = self.states.get("light.kitchen")
        if light:
            self.logger.info("State: %s", light.value)

        # Works for any domain, even unregistered ones
        custom = self.states.get("my_domain.some_entity")
        if custom:
            self.logger.info("Domain: %s, Value: %s", custom.domain, custom.value)
