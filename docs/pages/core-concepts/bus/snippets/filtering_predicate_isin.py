from hassette import App, conditions as C


class MediaPlayerApp(App):
    async def on_initialize(self):
        # Trigger if state is EITHER "playing" or "paused"
        self.bus.on_state_change(
            "media_player.living_room",
            handler=self.on_media_active,
            changed_to=C.IsIn(["playing", "paused"]),
        )

    async def on_media_active(self, event):
        pass
