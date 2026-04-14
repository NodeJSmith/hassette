from hassette import STATE_REGISTRY

state_dict = {
    "entity_id": "time.current",
    "state": "12:01:01",
}
time_state = STATE_REGISTRY.try_convert_state(state_dict)
# Result: TimeState with state=whenever.Time
