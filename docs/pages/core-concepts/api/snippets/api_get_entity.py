from hassette import App
from hassette.models import entities


class EntityApp(App):
    async def on_initialize(self):
        light = await self.api.get_entity("light.kitchen", entities.LightEntity)
        await light.turn_off()
