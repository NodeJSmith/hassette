from my_app import MyCustomState

from hassette import App


class GenericApp(App):
    async def on_initialize(self):
        # dictionary like access with state class
        my_instance = self.states[MyCustomState].get("work")
        if my_instance:
            self.logger.info("MyCustomState value: %s", my_instance.value)
