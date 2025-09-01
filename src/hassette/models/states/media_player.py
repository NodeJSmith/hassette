from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class MediaPlayerState(StringBaseState):
    class Attributes(AttributesBase):
        assumed_state: bool | None = Field(default=None)
        device_class: str | None = Field(default=None)
        adb_response: None = Field(default=None)
        hdmi_input: None = Field(default=None)

    domain: Literal["media_player"]

    attributes: Attributes | None = Field(default=None)
