from hassette import App
from hassette.models import entities


class EntityApp(App):
    async def on_initialize(self):
        light = await self.api.get_entity_or_none(
            "light.kitchen", entities.LightEntity
        )
        if light:
            await light.turn_off()
