from hassette import App, dependencies as D, states


class MotionApp(App):
    async def on_motion(
        self,
        event: D.TypedStateChangeEvent[states.BinarySensorState],
    ):
        entity_id = event.payload.data.entity_id
        new_value = event.payload.data.new_state.value
        self.logger.info("Motion: %s -> %s", entity_id, new_value)
