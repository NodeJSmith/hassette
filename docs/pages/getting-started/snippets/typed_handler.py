from hassette import App, AppConfig, D, states


class MyApp(App[AppConfig]):
    async def on_initialize(self):
        self.bus.on_state_change("sun.*", handler=self.on_sun_change)

    # --8<-- [start:typed-handler]
    async def on_sun_change(self, new_state: D.StateNew[states.SunState]):
        self.logger.info("Sun changed: %s", new_state.value)
        # --8<-- [end:typed-handler]
