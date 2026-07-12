from hassette import STATE_REGISTRY
from hassette.exceptions import InvalidEntityIdError

try:
    # Entity ID must have format "domain.entity"
    state = STATE_REGISTRY.try_convert_state({"entity_id": "invalid"})
except InvalidEntityIdError as exc:
    print(f"Invalid entity ID: {exc}")
