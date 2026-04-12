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

    async def button_pressed(self, new_state: D.StateNew[states.InputButtonState], entity_id: D.EntityId) -> None:
        friendly_name = new_state.attributes.friendly_name or entity_id
        self.logger.info("Button %s pressed at %s", friendly_name, new_state.last_changed)
