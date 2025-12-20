from hassette import App
from hassette.events import RawStateChangeEvent


class MotionApp(App):
    async def on_motion(self, event: RawStateChangeEvent):
        entity_id = event.payload.data.entity_id
        new_value = event.payload.data.get("new_state", {}).get("state")
        self.logger.info("Motion: %s -> %s", entity_id, new_value)
