from hassette import App


class MyApp(App):
    async def on_initialize(self):
        # Subscribe and save the subscription object
        subscription = self.bus.on_state_change("light.kitchen", handler=self.on_change)

        # Cancel when no longer needed
        subscription.cancel()

    async def on_change(self):
        pass
