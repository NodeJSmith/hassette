from hassette import App, C, P


class LightApp(App):
    async def on_initialize(self):
        # Fire when a light turns on from any off-like state
        self.bus.on_state_change(
            "light.living_room",
            handler=self.on_light_turned_on,
            where=[
                P.StateFrom(C.IsIn(["off", "unavailable"])),
                P.StateTo("on"),
            ],
        )

    async def on_light_turned_on(self, event):
        self.logger.info("Living room light turned on")
