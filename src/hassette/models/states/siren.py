from enum import IntFlag, StrEnum
from typing import Literal

from pydantic import Field

from .base import AttributesBase, BoolBaseState


class SirenEntityCapabilityAttribute(StrEnum):
    AVAILABLE_TONES = "available_tones"


class SirenEntityFeature(IntFlag):
    TURN_ON = 1
    TURN_OFF = 2
    TONES = 4
    VOLUME_SET = 8
    DURATION = 16


class SirenAttributes(AttributesBase):
    available_tones: list[int | str] | dict[int, str] | None = Field(default=None)

    @property
    def supports_turn_on(self) -> bool:
        return self.has_feature(SirenEntityFeature.TURN_ON)

    @property
    def supports_turn_off(self) -> bool:
        return self.has_feature(SirenEntityFeature.TURN_OFF)

    @property
    def supports_tones(self) -> bool:
        return self.has_feature(SirenEntityFeature.TONES)

    @property
    def supports_volume_set(self) -> bool:
        return self.has_feature(SirenEntityFeature.VOLUME_SET)

    @property
    def supports_duration(self) -> bool:
        return self.has_feature(SirenEntityFeature.DURATION)


class SirenState(BoolBaseState):
    """Representation of a Home Assistant siren state.

    See: https://www.home-assistant.io/integrations/siren/
    """

    domain: Literal["siren"]

    attributes: SirenAttributes
