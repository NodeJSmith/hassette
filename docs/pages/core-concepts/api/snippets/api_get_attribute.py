from hassette import App, MISSING_VALUE


class BrightnessApp(App):
    async def on_initialize(self):
        brightness = await self.api.get_attribute("light.kitchen", "brightness")
        if brightness is not MISSING_VALUE:
            self.logger.info("Brightness: %s", brightness)

        # Dot-path: index into a list attribute
        first_effect = await self.api.get_attribute("light.kitchen", "effect_list.0")
        self.logger.info("First available effect: %s", first_effect)
