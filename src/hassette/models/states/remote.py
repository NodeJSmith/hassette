from enum import IntFlag, StrEnum
from typing import Literal

from pydantic import Field

from .base import AttributesBase, BoolBaseState


class RemoteEntityStateAttribute(StrEnum):
    ACTIVITY_LIST = "activity_list"
    CURRENT_ACTIVITY = "current_activity"


class RemoteEntityFeature(IntFlag):
    LEARN_COMMAND = 1
    DELETE_COMMAND = 2
    ACTIVITY = 4


class RemoteAttributes(AttributesBase):
    activity_list: list[str] | None = Field(default=None)
    current_activity: str | None = Field(default=None)

    @property
    def supports_learn_command(self) -> bool:
        return self.has_feature(RemoteEntityFeature.LEARN_COMMAND)

    @property
    def supports_delete_command(self) -> bool:
        return self.has_feature(RemoteEntityFeature.DELETE_COMMAND)

    @property
    def supports_activity(self) -> bool:
        return self.has_feature(RemoteEntityFeature.ACTIVITY)


class RemoteState(BoolBaseState):
    """Representation of a Home Assistant remote state.

    See: https://www.home-assistant.io/integrations/remote/
    """

    domain: Literal["remote"]

    attributes: RemoteAttributes
