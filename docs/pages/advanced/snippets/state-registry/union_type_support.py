from hassette import dependencies as D, states


async def on_sensor_change(
    self,
    new_state: D.StateNew[states.SensorState | states.BinarySensorState],
):
    # StateRegistry determines the correct type based on domain
    if new_state.domain == "sensor":
        # new_state is SensorState
        value = float(new_state.state)
    else:
        # new_state is BinarySensorState
        is_on = new_state.state == "on"
