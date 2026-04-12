from hassette import App, AppConfig


class SubscribeApp(App[AppConfig]):
    async def on_initialize(self):
        # --8<-- [start:subscribe_state_change]
        self.on_change_listener = self.bus.on_state_change(self.app_config.light, handler=self.on_change)
        # --8<-- [end:subscribe_state_change]

    async def on_change(self, event):
        pass
