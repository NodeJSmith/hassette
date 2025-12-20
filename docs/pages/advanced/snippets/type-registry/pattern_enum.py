from enum import Enum

from hassette.core.type_registry import register_type_converter_fn


class FanSpeed(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@register_type_converter_fn
def str_to_fan_speed(value: str) -> FanSpeed:
    """Convert string to FanSpeed enum.

    Types inferred from signature: str → FanSpeed
    """
    return FanSpeed(value.lower())
