from hassette import STATE_REGISTRY
from hassette.exceptions import (
    InvalidDataForStateConversionError,
    InvalidEntityIdError,
    UnableToConvertStateError,
)

# Invalid Data
try:
    state = STATE_REGISTRY.try_convert_state(None)  # Invalid data
except InvalidDataForStateConversionError as e:
    print(f"Invalid state data: {e}")

# Invalid Entity ID
try:
    # Entity ID must have format "domain.entity"
    state = STATE_REGISTRY.try_convert_state({"entity_id": "invalid"})
except InvalidEntityIdError as e:
    print(f"Invalid entity ID: {e}")

# Unable to Convert
data = {"entity_id": "light.bedroom", "state": "on"}  # Simplified data
try:
    state = STATE_REGISTRY.try_convert_state(data)
except UnableToConvertStateError as e:
    print(f"Conversion failed: {e}")
    # Falls back to BaseState or re-raises depending on context
