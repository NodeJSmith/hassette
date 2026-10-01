from hassette import STATE_REGISTRY
from hassette.exceptions import InvalidDataForStateConversionError

event_envelope = {"event": {"event_type": "state_changed", "data": {}}}

try:
    state = STATE_REGISTRY.try_convert_state(event_envelope)
except InvalidDataForStateConversionError as exc:
    print(f"Invalid state data: {exc}")
