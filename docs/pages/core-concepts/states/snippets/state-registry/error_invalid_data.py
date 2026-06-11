from hassette import STATE_REGISTRY
from hassette.exceptions import InvalidDataForStateConversionError

try:
    state = STATE_REGISTRY.try_convert_state(None)
except InvalidDataForStateConversionError as e:
    print(f"Invalid state data: {e}")
