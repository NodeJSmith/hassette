from hassette import App


class ConversionApp(App):
    async def on_initialize(self):
        # Convert a value
        converted_value = self.type_registry.convert("42", int)
        self.logger.info("Converted value: %s", converted_value)
