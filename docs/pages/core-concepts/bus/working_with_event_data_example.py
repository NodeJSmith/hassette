from typing import reveal_type

from hassette import App, states
from hassette import dependencies as D


class WorkingWithEventDataExample(App):
    async def on_light_change(
        self,
        new_state: D.StateNew[states.LightState],
        old_state: D.MaybeStateOld[states.LightState],
        new_state_value: D.StateValueNew[str],
        old_state_value: D.MaybeStateValueOld[str],
    ) -> None:
        self.logger.info("%s changed from %s to %s", new_state.entity_id, old_state_value, new_state_value)

        reveal_type(new_state)  # LightState

        reveal_type(old_state)  # LightState | None

        reveal_type(new_state_value)  # str
        reveal_type(old_state_value)  # str | None

        self.logger.info("%s changed from %s to %s", new_state.entity_id, old_state_value, new_state_value)
