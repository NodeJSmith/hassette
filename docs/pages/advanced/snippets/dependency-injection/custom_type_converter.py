from enum import Enum
from typing import Annotated

from hassette import App, accessors as A
from hassette.core.type_registry import register_type_converter_fn


class FanSpeed(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@register_type_converter_fn(error_message="'{value}' is not a valid FanSpeed")
def str_to_fan_speed(value: str) -> FanSpeed:
    """Convert string to FanSpeed enum.

    Types are inferred from the function signature.
    """
    return FanSpeed(value.lower())


# Now you can use it in handlers
class FanApp(App):
    async def on_fan_change(
        self,
        # String "high" → FanSpeed.HIGH (automatic)
        speed: Annotated[FanSpeed, A.get_attr_new("speed")],
    ):
        self.logger.info("Fan speed: %s", speed.value)
