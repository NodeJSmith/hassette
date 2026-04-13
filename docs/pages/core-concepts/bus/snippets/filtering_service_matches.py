from hassette import App, P


class SceneApp(App):
    async def on_initialize(self):
        # Match any scene.turn_on call, regardless of service data
        self.bus.on(topic="call_service", handler=self.on_any_scene, where=P.ServiceMatches("scene.turn_on"))

        # Combine with ServiceDataWhere for full filtering
        self.bus.on(
            topic="call_service",
            handler=self.on_evening_scene,
            where=[
                P.ServiceMatches("scene.turn_on"),
                P.ServiceDataWhere({"entity_id": "scene.evening"}),
            ],
        )

    async def on_any_scene(self, event):
        self.logger.info("A scene was activated")

    async def on_evening_scene(self, event):
        self.logger.info("Evening scene activated")
