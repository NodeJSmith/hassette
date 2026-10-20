from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class GroupAttributes(AttributesBase):
    entity_id: list[str] | None = Field(default=None)
    order: int | None = Field(default=None)
    auto: bool | None = Field(default=None)


class GroupState(StringBaseState):
    """Representation of a Home Assistant group state.

    See: https://www.home-assistant.io/integrations/group/
    """

    domain: Literal["group"]

    attributes: GroupAttributes
