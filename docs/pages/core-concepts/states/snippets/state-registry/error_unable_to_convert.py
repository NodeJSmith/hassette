from hassette import STATE_REGISTRY
from hassette.exceptions import UnableToConvertStateError

data = {"entity_id": "light.bedroom", "state": "on"}  # Simplified data
try:
    state = STATE_REGISTRY.try_convert_state(data)
except UnableToConvertStateError as e:
    print(f"Conversion failed: {e}")
    # Falls back to BaseState or re-raises depending on context
