from typing import Annotated

from hassette import A, App, D


class MyExtApp(App):
    async def handler(
        self,
        # Brightness is returned as a string from HA, but TypeRegistry
        # automatically converts it to int based on the type hint
        brightness: Annotated[int | None, A.get_attr_new("brightness")],
        entity_id: D.EntityId,
    ):
        if brightness and brightness > 200:
            self.logger.info("%s is very bright: %d", entity_id, brightness)
