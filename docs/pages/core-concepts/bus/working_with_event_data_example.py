from typing import reveal_type

from hassette import App, states
from hassette import dependencies as D


class WorkingWithEventDataExample(App):
    async def on_light_change(
        self, new_state: D.StateNew[states.LightState], old_state: D.MaybeStateOld[states.LightState]
    ) -> None:
        self.logger.info("%s changed from %s to %s", new_state.entity_id)

        reveal_type(new_state)  # LightState

        reveal_type(old_state)  # LightState | None

        new_state_value = new_state.value
        old_state_value = old_state.value if old_state is not None else None

        self.logger.info("%s changed from %s to %s", new_state.entity_id, old_state_value, new_state_value)
