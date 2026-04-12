from hassette import App


class MyApp(App):
    async def on_initialize(self):
        value = "example"

        self.logger.info("This is a log message")
        self.logger.info("Value: %s", value)
        self.logger.error("Something went wrong")
