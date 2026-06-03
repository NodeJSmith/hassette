from hassette import STATE_REGISTRY
from hassette.exceptions import InvalidDataForStateConversionError

try:
    state = STATE_REGISTRY.try_convert_state(None)  # pyright: ignore[reportArgumentType]
except InvalidDataForStateConversionError as e:
    print(f"Invalid state data: {e}")
