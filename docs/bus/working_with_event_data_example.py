from hassette import App
from hassette.events import StateChangeEvent


class WorkingWithEventDataExample(App):
    async def on_motion(self, event: StateChangeEvent) -> None:
        data = event.payload.data  # type: StateChangePayload
        entity_id = data.entity_id
        old_state = data.old_state  # Full state object with .value, .attributes, etc.
        new_state = data.new_state  # Full state object with .value, .attributes, etc.

        self.logger.info("%s changed from %s to %s", entity_id, old_state.value, new_state.value)
