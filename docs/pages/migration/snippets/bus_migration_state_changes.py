from hassette import App, AppConfig, D, states


class MyConfig(AppConfig):
    motion_entity: str = "binary_sensor.motion"


class MyApp(App[MyConfig]):
    async def on_initialize(self):
        self.bus.on_state_change(
            "binary_sensor.motion",
            handler=self.on_motion,
            changed_to="on",
        )

    async def on_motion(self, new_state: D.StateNew[states.BinarySensorState]):
        self.logger.info("Motion detected on %s", new_state.entity_id)
