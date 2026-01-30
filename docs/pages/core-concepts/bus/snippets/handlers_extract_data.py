from hassette import App, states
from hassette import dependencies as D


class MotionApp(App):
    async def on_motion(
        self,
        new_state: D.StateNew[states.BinarySensorState],
        entity_id: D.EntityId,
    ):
        friendly_name = new_state.attributes.friendly_name or entity_id
        self.logger.info("Motion detected: %s", friendly_name)
