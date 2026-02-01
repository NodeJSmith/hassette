from hassette import App
from hassette.events import RawStateChangeEvent


class MotionApp(App):
    async def on_motion(self, event: RawStateChangeEvent):
        entity_id = event.payload.data.entity_id
        new_value = event.payload.data.new_state.get("state") if event.payload.data.new_state else None
        self.logger.info("Motion: %s -> %s", entity_id, new_value)
