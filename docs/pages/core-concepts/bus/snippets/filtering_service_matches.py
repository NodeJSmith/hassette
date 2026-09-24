from hassette import App, P, Topic


class SceneApp(App):
    async def on_initialize(self):
        # Match any scene.turn_on call, regardless of service data
        await self.bus.on(
            topic=Topic.HASS_EVENT_CALL_SERVICE,
            handler=self.on_any_scene,
            where=[P.DomainMatches("scene"), P.ServiceMatches("turn_on")],
            name="any_scene",
        )

        # Combine with ServiceDataWhere for full filtering
        await self.bus.on(
            topic=Topic.HASS_EVENT_CALL_SERVICE,
            handler=self.on_evening_scene,
            where=[
                P.DomainMatches("scene"),
                P.ServiceMatches("turn_on"),
                P.ServiceDataWhere({"entity_id": "scene.evening"}),
            ],
            name="evening_scene",
        )

    async def on_any_scene(self, event):
        self.logger.info("A scene was activated")

    async def on_evening_scene(self, event):
        self.logger.info("Evening scene activated")
