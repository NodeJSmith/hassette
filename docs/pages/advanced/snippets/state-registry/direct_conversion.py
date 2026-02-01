from hassette import STATE_REGISTRY

# Raw state data from Home Assistant
state_dict = {
    "entity_id": "light.bedroom",
    "state": "on",
    "attributes": {"brightness": 200},
    # ... more fields
}

# Convert to typed model
light_state = STATE_REGISTRY.try_convert_state(state_dict)
# Returns: LightState instance
