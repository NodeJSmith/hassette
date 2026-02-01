from typing import Annotated

from hassette import A, App, C


class MediaPlayerApp(App):
    async def on_initialize(self):
        self.bus.on_attribute_change(
            "media_player.living_room_tv",
            "app_name",
            handler=self.on_app_name_change,
            changed_to=C.IsIn(["Home Assistant Lovelace", "Netflix"]),
        )

    async def on_app_name_change(
        self,
        old_app_name: Annotated[str, A.get_attr_old("app_name")],
        app_name: Annotated[str, A.get_attr_new("app_name")],
    ):
        self.logger.info("App name changed from %s to %s", old_app_name, app_name)
