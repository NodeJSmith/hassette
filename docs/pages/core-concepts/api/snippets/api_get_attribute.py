from hassette import App, MISSING_VALUE


class BrightnessApp(App):
    async def on_initialize(self):
        brightness = await self.api.get_attribute("light.kitchen", "brightness")
        if brightness is not MISSING_VALUE:
            self.logger.info("Brightness: %s", brightness)

        # Dot-path for nested attributes
        color_mode = await self.api.get_attribute("light.kitchen", "color_mode")
        self.logger.info("Color mode: %s", color_mode)
