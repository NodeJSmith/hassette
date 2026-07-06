from enum import StrEnum
from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class TextEntityCapabilityAttribute(StrEnum):
    MODE = "mode"
    MIN = "min"
    MAX = "max"
    PATTERN = "pattern"


class TextMode(StrEnum):
    PASSWORD = "password"
    TEXT = "text"


class TextAttributes(AttributesBase):
    mode: TextMode | None = Field(default=None)
    native_value: str | None = Field(default=None)
    native_min: int | None = Field(default=None)
    native_max: int | None = Field(default=None)
    pattern: str | None = Field(default=None)


class TextState(StringBaseState):
    """Representation of a Home Assistant text state.

    See: https://www.home-assistant.io/integrations/text/
    """

    domain: Literal["text"]

    attributes: TextAttributes
