from hassette import App


class ConversionApp(App):
    async def on_initialize(self):
        # Convert a value
        result = self.type_registry.convert("42", int)  # Returns 42 as int
