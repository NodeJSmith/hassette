from typing import reveal_type

from hassette import App, states
from hassette.events import StateChangeEvent


class WorkingWithEventDataExample(App):
    async def on_motion(self, event: StateChangeEvent[states.StateUnion]) -> None:
        data = event.payload.data
        entity_id = data.entity_id
        reveal_type(data.old_state)  # Full state object with .value, .attributes, etc.
        reveal_type(data.new_state)  # Full state object with .value, .attributes, etc.

        self.logger.info("%s changed from %s to %s", entity_id, data.old_state_value, data.new_state_value)
