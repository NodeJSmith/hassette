from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class SirenAttributes(AttributesBase):
    available_tones: list[str] | None = Field(default=None)


class SirenState(StringBaseState):
    """Representation of a Home Assistant siren state.

    See: https://www.home-assistant.io/integrations/siren/
    """

    domain: Literal["siren"]

    attributes: SirenAttributes
