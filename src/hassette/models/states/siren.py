from typing import Literal

from pydantic import Field

from .base import AttributesBase, BoolBaseState


class SirenAttributes(AttributesBase):
    available_tones: list[str] | None = Field(default=None)


class SirenState(BoolBaseState):
    """Representation of a Home Assistant siren state.

    See: https://www.home-assistant.io/integrations/siren/
    """

    domain: Literal["siren"]

    attributes: SirenAttributes
