from hassette import App
from hassette.events import RawStateChangeEvent


class MotionApp(App):
    async def on_motion(self, event: RawStateChangeEvent):
        entity_id = event.payload.data.entity_id
        new_state_dict = event.payload.data.new_state
        state_value = new_state_dict.get("state") if new_state_dict else None
        self.logger.info("Motion: %s -> %s", entity_id, state_value)
