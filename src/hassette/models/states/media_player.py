from typing import Any, Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class MediaPlayerAttributes(AttributesBase):
    assumed_state: bool | None = Field(default=None)
    adb_response: Any | None = Field(default=None)
    hdmi_input: Any | None = Field(default=None)


class MediaPlayerState(StringBaseState):
    """Representation of a Home Assistant media_player state.

    See: https://www.home-assistant.io/integrations/media_player/
    """

    domain: Literal["media_player"]

    attributes: MediaPlayerAttributes
