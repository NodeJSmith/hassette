from hassette import App, AppConfig


class ImmediateFireApp(App[AppConfig]):
    async def on_initialize(self):
        # --8<-- [start:immediate_fire]
        # Fire now if the light is already on, then continue listening
        self.bus.on_state_change(
            "light.living_room",
            handler=self.on_light_on,
            changed_to="on",
            immediate=True,
        )

        # Combine with once=True: fire at most once, immediately if already matching
        self.bus.on_state_change(
            "input_boolean.setup_complete",
            handler=self.on_setup_done,
            changed_to="on",
            immediate=True,
            once=True,
        )
        # --8<-- [end:immediate_fire]

    async def on_light_on(self):
        pass

    async def on_setup_done(self):
        pass
