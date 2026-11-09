from enum import IntFlag, StrEnum
from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class CameraEntityStateAttribute(StrEnum):
    ACCESS_TOKEN = "access_token"
    MODEL_NAME = "model_name"
    BRAND = "brand"
    MOTION_DETECTION = "motion_detection"


class CameraStateValue(StrEnum):
    RECORDING = "recording"
    STREAMING = "streaming"
    IDLE = "idle"


class StreamType(StrEnum):
    HLS = "hls"
    WEB_RTC = "web_rtc"


class CameraService(StrEnum):
    DISABLE_MOTION_DETECTION = "disable_motion_detection"
    ENABLE_MOTION_DETECTION = "enable_motion_detection"
    PLAY_STREAM = "play_stream"
    RECORD = "record"
    SNAPSHOT = "snapshot"
    TURN_OFF = "turn_off"
    TURN_ON = "turn_on"


class CameraServiceArgument(StrEnum):
    DURATION = "duration"
    FILENAME = "filename"
    FORMAT = "format"
    LOOKBACK = "lookback"
    MEDIA_PLAYER = "media_player"


class CameraEntityFeature(IntFlag):
    ON_OFF = 1
    STREAM = 2


class CameraAttributes(AttributesBase):
    brand: str | None = Field(default=None)
    frame_interval: float | None = Field(default=None)
    is_on: bool | None = Field(default=None)
    is_recording: bool | None = Field(default=None)
    is_streaming: bool | None = Field(default=None)
    model: str | None = Field(default=None)
    motion_detection: bool | None = Field(default=None)
    should_poll: bool | None = Field(default=None)

    @property
    def supports_on_off(self) -> bool:
        return self.has_feature(CameraEntityFeature.ON_OFF)

    @property
    def supports_stream(self) -> bool:
        return self.has_feature(CameraEntityFeature.STREAM)


class CameraState(StringBaseState):
    """Representation of a Home Assistant camera state.

    See: https://www.home-assistant.io/integrations/camera/
    """

    domain: Literal["camera"]

    attributes: CameraAttributes
