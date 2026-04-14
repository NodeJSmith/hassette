from enum import StrEnum, auto
from typing import Annotated

from hassette import A, App, register_type_converter_fn


class Effect(StrEnum):
    BLINK = auto()
    BREATHE = auto()
    CANDLE = auto()
    CHANNEL_CHANGE = auto()
    COLORLOOP = auto()
    FINISH_EFFECT = auto()
    FIREPLACE = auto()
    OKAY = auto()
    STOP_EFFECT = auto()
    STOP_HUE_EFFECT = auto()


@register_type_converter_fn(error_message="'{value}' is not a valid Effect")
def str_to_effect(value: str) -> Effect:
    """Convert string to Effect enum.

    Types are inferred from the function signature.
    """
    return Effect(value.lower())


# Now you can use it in handlers


class LightEffectApp(App):
    async def on_light_effect_change(self, effect: Annotated[Effect, A.get_attr_new("effect")]):
        self.logger.info("Light effect: %r", effect)
