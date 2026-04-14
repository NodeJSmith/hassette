from hassette import App, AppConfig, D, states


class MyConfig(AppConfig):
    button_entity: str = "input_button.test_button"


class MyApp(App[MyConfig]):
    async def on_initialize(self):
        sub = self.bus.on_state_change(
            entity_id=self.app_config.button_entity,
            handler=self.button_pressed,
        )
        self.logger.info("Subscribed: %s", sub)

    async def button_pressed(self, event: D.TypedStateChangeEvent[states.InputButtonState]) -> None:
        self.logger.info("Button pressed: %s", event)
