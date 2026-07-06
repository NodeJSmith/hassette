from enum import IntFlag, StrEnum
from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class CoverEntityStateAttribute(StrEnum):
    IS_CLOSED = "is_closed"
    CURRENT_POSITION = "current_position"
    CURRENT_TILT_POSITION = "current_tilt_position"


class CoverStateValue(StrEnum):
    CLOSED = "closed"
    CLOSING = "closing"
    OPEN = "open"
    OPENING = "opening"


class CoverDeviceClass(StrEnum):
    AWNING = "awning"
    BLIND = "blind"
    CURTAIN = "curtain"
    DAMPER = "damper"
    DOOR = "door"
    GARAGE = "garage"
    GATE = "gate"
    SHADE = "shade"
    SHUTTER = "shutter"
    WINDOW = "window"


class CoverEntityFeature(IntFlag):
    OPEN = 1
    CLOSE = 2
    SET_POSITION = 4
    STOP = 8
    OPEN_TILT = 16
    CLOSE_TILT = 32
    STOP_TILT = 64
    SET_TILT_POSITION = 128


class CoverAttributes(AttributesBase):
    current_cover_position: int | None = Field(default=None)
    current_cover_tilt_position: int | None = Field(default=None)
    device_class: CoverDeviceClass | None = Field(default=None)
    is_closed: bool | None = Field(default=None)
    is_closing: bool | None = Field(default=None)
    is_opening: bool | None = Field(default=None)

    @property
    def supports_open(self) -> bool:
        return self.has_feature(CoverEntityFeature.OPEN)

    @property
    def supports_close(self) -> bool:
        return self.has_feature(CoverEntityFeature.CLOSE)

    @property
    def supports_set_position(self) -> bool:
        return self.has_feature(CoverEntityFeature.SET_POSITION)

    @property
    def supports_stop(self) -> bool:
        return self.has_feature(CoverEntityFeature.STOP)

    @property
    def supports_open_tilt(self) -> bool:
        return self.has_feature(CoverEntityFeature.OPEN_TILT)

    @property
    def supports_close_tilt(self) -> bool:
        return self.has_feature(CoverEntityFeature.CLOSE_TILT)

    @property
    def supports_stop_tilt(self) -> bool:
        return self.has_feature(CoverEntityFeature.STOP_TILT)

    @property
    def supports_set_tilt_position(self) -> bool:
        return self.has_feature(CoverEntityFeature.SET_TILT_POSITION)


class CoverState(StringBaseState):
    """Representation of a Home Assistant cover state.

    See: https://www.home-assistant.io/integrations/cover/
    """

    domain: Literal["cover"]

    attributes: CoverAttributes
