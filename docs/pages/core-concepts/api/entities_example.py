from hassette import App
from hassette.models.entities import LightEntity


class EntitiesExample(App):
    async def entities_example(self):
        light = await self.api.get_entity("light.bedroom", LightEntity)
        await light.turn_on(brightness_pct=30)

        maybe = await self.api.get_entity_or_none("light.guest", LightEntity)
        if maybe is None:
            self.logger.warning("Guest light is not registered")

        return light, maybe
