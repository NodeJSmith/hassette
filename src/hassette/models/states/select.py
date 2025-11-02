from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class SelectState(StringBaseState):
    """Representation of a Home Assistant select state.

    See: https://www.home-assistant.io/integrations/select/
    """

    class Attributes(AttributesBase):
        options: list[str] | None = Field(default=None)

    domain: Literal["select"]

    attributes: Attributes
