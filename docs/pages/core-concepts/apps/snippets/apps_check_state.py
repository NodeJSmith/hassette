from hassette import App, AppConfig


class CheckStateApp(App[AppConfig]):
    async def on_initialize(self):
        # --8<-- [start:check_state]
        current_state = self.states.light["light.kitchen"].value
        self.logger.info("Current state: %s", current_state)
        # --8<-- [end:check_state]
