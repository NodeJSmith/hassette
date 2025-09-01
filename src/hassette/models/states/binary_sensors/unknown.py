from typing import Literal

from pydantic import AliasPath, ConfigDict, Field

from hassette.models.states.binary_sensors.base import BinarySensor_BaseState


class BinarySensor_UnknownState(BinarySensor_BaseState):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    device_class: Literal[None] = Field(None, validation_alias=AliasPath("attributes", "device_class"))
    domain: Literal["binary_sensor"]
