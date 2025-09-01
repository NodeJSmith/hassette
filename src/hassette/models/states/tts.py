from typing import Literal

from pydantic import Field
from whenever import Instant

from .base import AttributesBase, BaseState


class TtsState(BaseState[Instant | None]):
    domain: Literal["tts"]

    attributes: AttributesBase | None = Field(default=None)
