from hassette import App, StateChangeEvent, states


class BusEventExample(App):
    async def on_motion(self, event: StateChangeEvent[states.BinarySensorState]) -> None:
        data = event.payload.data
        self.logger.info("%s changed from %s to %s", event.topic, data.old_state.value, data.new_state.value)
