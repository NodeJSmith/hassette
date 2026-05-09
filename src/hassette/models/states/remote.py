from typing import Literal

from pydantic import Field

from .base import AttributesBase, BoolBaseState


class RemoteAttributes(AttributesBase):
    activity_list: list | None = Field(default=None)
    current_activity: str | None = Field(default=None)


class RemoteState(BoolBaseState):
    """Representation of a Home Assistant remote state.

    See: https://www.home-assistant.io/integrations/remote/
    """

    domain: Literal["remote"]

    attributes: RemoteAttributes
