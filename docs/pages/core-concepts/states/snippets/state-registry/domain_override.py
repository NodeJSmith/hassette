from typing import Literal

from hassette.models.states import SensorAttributes, SensorState


class CustomSensorAttributes(SensorAttributes):
    custom_field: str | None = None


class CustomSensorState(SensorState):
    """Extended sensor state with custom attributes."""

    domain: Literal["sensor"]
    attributes: CustomSensorAttributes
