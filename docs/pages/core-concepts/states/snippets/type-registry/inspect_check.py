from hassette import App


class ConversionApp(App):
    async def on_initialize(self):
        # Check if a converter exists
        key = (str, int)
        if key in self.type_registry.conversion_map:
            entry = self.type_registry.conversion_map[key]
            self.logger.info("Converter found for %s -> %s", str, int)
        else:
            self.logger.info("No converter registered")
