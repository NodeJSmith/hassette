from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class AssistSatelliteState(StringBaseState):
    class Attributes(AttributesBase):
        restored: bool | None = Field(default=None)

    domain: Literal["assist_satellite"]

    attributes: Attributes
