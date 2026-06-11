from hassette import STATE_REGISTRY

state_dict = {
    "entity_id": "binary_sensor.front_door",
    "state": "on",
}
door_state = STATE_REGISTRY.try_convert_state(state_dict)  # pyright: ignore[reportArgumentType]
# Result: BinarySensorState with value=True
