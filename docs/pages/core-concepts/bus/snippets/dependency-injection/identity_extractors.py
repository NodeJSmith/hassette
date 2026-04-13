from hassette import App, D


class LightApp(App):
    async def on_any_light(self, entity_id: D.EntityId, domain: D.Domain):
        self.logger.info("Light entity %s in domain %s changed", entity_id, domain)
