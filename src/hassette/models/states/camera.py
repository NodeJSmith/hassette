from enum import IntFlag, StrEnum
from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class CameraStateValue(StrEnum):
    RECORDING = "recording"
    STREAMING = "streaming"
    IDLE = "idle"


class StreamType(StrEnum):
    HLS = "hls"
    WEB_RTC = "web_rtc"


class CameraEntityFeature(IntFlag):
    ON_OFF = 1
    STREAM = 2


class CameraAttributes(AttributesBase):
    brand: str | None = Field(default=None)
    frame_interval: float = Field(default=None)
    is_on: bool = Field(default=None)
    is_recording: bool = Field(default=None)
    is_streaming: bool = Field(default=None)
    model: str | None = Field(default=None)
    motion_detection_enabled: bool = Field(default=None)
    should_poll: bool = Field(default=None)
    state: None = Field(default=None)

    @property
    def supports_on_off(self) -> bool:
        return self._has_feature(CameraEntityFeature.ON_OFF)

    @property
    def supports_stream(self) -> bool:
        return self._has_feature(CameraEntityFeature.STREAM)


class CameraState(StringBaseState):
    """Representation of a Home Assistant camera state.

    See: https://www.home-assistant.io/integrations/camera/
    """

    domain: Literal["camera"]

    attributes: CameraAttributes
