from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class SirenState(StringBaseState):
    class Attributes(AttributesBase):
        available_tones: list[str] | None = Field(default=None)

    domain: Literal["siren"]

    attributes: Attributes
