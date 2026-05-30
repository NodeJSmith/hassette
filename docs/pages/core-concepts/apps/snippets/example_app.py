from hassette import App, AppConfig, D, states


class ExampleApp(App[AppConfig]):
    async def on_initialize(self):
        self.logger.info("Hello from ExampleApp!")

        # Subscribe using the bus helper
        await self.bus.on_state_change(
            "light.living_room",
            handler=self.on_light_change,
            name="living_room_light",
        )

    async def on_light_change(
        self,
        new_state: D.StateNew[states.LightState],
    ):
        self.logger.info("Light changed to %s", new_state.value)
