from hassette import App, dependencies as D, states


class MotionApp(App):
    async def on_motion(
        self,
        event: D.TypedStateChangeEvent[states.BinarySensorState],
    ):
        entity_id = event.payload.data.entity_id
        new_state = event.payload.data.new_state
        if new_state:
            state_value = new_state.value
            self.logger.info("Motion: %s -> %s", entity_id, state_value)
