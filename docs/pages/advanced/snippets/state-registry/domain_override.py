from typing import ClassVar

from hassette.models.states import SensorAttributes, SensorState


class CustomSensorAttributes(SensorAttributes):
    custom_field: str | None = None


class CustomSensorState(SensorState):
    """Extended sensor state with custom attributes."""

    domain: ClassVar[str] = "sensor"
    attributes: CustomSensorAttributes
