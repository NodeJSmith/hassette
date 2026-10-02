from hassette import STATE_REGISTRY

state_dict = {
    "entity_id": "binary_sensor.front_door",
    "state": "on",
    "attributes": {},
    "context": {"id": "01J0000000000000000000000", "parent_id": None, "user_id": None},
}
door_state = STATE_REGISTRY.try_convert_state(state_dict)
# Result: BinarySensorState with value=True
