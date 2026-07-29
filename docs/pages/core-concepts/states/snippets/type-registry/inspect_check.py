from hassette import App


class ConversionApp(App):
    async def on_initialize(self):
        # Check if a converter exists
        converter_key = (str, int)
        if converter_key in self.type_registry.conversion_map:
            converter_entry = self.type_registry.conversion_map[converter_key]
            self.logger.info("Converter found: %s", converter_entry)
        else:
            self.logger.info("No converter registered")
