from typing import Any, Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class MediaPlayerState(StringBaseState):
    class Attributes(AttributesBase):
        assumed_state: bool | None = Field(default=None)
        adb_response: Any | None = Field(default=None)
        hdmi_input: Any | None = Field(default=None)

    domain: Literal["media_player"]
