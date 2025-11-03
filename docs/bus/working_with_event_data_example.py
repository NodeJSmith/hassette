from typing import reveal_type

from hassette import App, states
from hassette.events import StateChangeEvent


class WorkingWithEventDataExample(App):
    async def on_motion(self, event: StateChangeEvent[states.LightState]) -> None:
        data = event.payload.data
        entity_id = data.entity_id
        reveal_type(data.old_state)  # LightState | None
        reveal_type(data.new_state)  # LightState | None

        # has_state is a TypeGuard that lets us narrow the type
        if data.has_state(data.old_state):
            reveal_type(data.old_state)  # LightState

        # whereas has_old_state / has_new_state are simple bools
        if data.has_old_state:
            reveal_type(data.old_state)  # LightState | None

        # if you just need to know the state value or if it's missing
        # you can use old_state_value / new_state_value
        # the MISSING_VALUE sentinel is a subclass of Sentinel that is Falsey
        # so you can use it in boolean contexts directly
        # this allows None to remain a valid value

        reveal_type(data.old_state_value)  # LightState | MISSING_VALUE
        reveal_type(data.new_state_value)  # LightState | MISSING_VALUE

        self.logger.info("%s changed from %s to %s", entity_id, data.old_state_value, data.new_state_value)
