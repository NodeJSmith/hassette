from hassette import App, D, states


class SensorApp(App):
    async def on_sensor_change(self, new_state: D.StateNew[states.SensorState | states.BinarySensorState]):
        # StateRegistry determines the correct type based on domain
        if new_state.domain == "sensor" and new_state.value:
            # new_state is SensorState
            float(new_state.value)
        else:
            # new_state is BinarySensorState
            pass
