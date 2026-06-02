from hassette import App, AppConfig, D, P, states


class VolumeApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        # Fire when volume changes on a specific media player
        await self.bus.on_attribute_change(
            "media_player.living_room",
            "volume_level",
            handler=self.on_volume_change,
            name="living_room_volume",
        )

        # Fire when brightness increases using a predicate
        await self.bus.on_attribute_change(
            "light.kitchen",
            "brightness",
            handler=self.on_brightness_up,
            where=P.AttrDidChange("brightness"),
            name="kitchen_brightness_up",
        )

    async def on_volume_change(
        self,
        new: D.StateNew[states.MediaPlayerState],
    ) -> None:
        volume = new.attributes.volume_level
        self.logger.info("Volume: %s", volume)

    async def on_brightness_up(self, event) -> None:
        pass
