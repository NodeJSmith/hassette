from hassette import App, AppConfig, StateChangeEvent, states


class MyConfig(AppConfig):
    pass


class MyApp(App[MyConfig]):
    async def on_initialize(self):
        # React when any light changes
        self.bus.on_state_change("sun.*", handler=self.changed)

    async def changed(self, event: StateChangeEvent[states.SunState]):
        self.logger.info("Sun changed: %s", event.payload.data)
