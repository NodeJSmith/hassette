from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class SelectAttributes(AttributesBase):
    options: list[str] | None = Field(default=None)


class SelectState(StringBaseState):
    """Representation of a Home Assistant select state.

    See: https://www.home-assistant.io/integrations/select/
    """

    domain: Literal["select"]

    attributes: SelectAttributes
