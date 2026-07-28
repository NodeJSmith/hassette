from hassette import App, P, RawStateChangeEvent


class LightApp(App):
    async def on_initialize(self):
        # `&` is AllOf, `|` is AnyOf, `~` is Not
        await self.bus.on_state_change(
            "light.*",
            handler=self.on_light_change,
            where=(P.StateTo("on") | P.StateTo("unavailable"))
            & ~P.EntityMatches("light.office"),
            name="lights_except_office",
        )

    async def on_light_change(self, event: RawStateChangeEvent):
        self.logger.info("Light changed: %s", event.payload.data.entity_id)
