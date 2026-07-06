from enum import StrEnum
from typing import Literal

from pydantic import Field

from .base import AttributesBase, NumericBaseState


class NumberEntityCapabilityAttribute(StrEnum):
    MIN = "min"
    MAX = "max"
    STEP = "step"
    MODE = "mode"


class NumberMode(StrEnum):
    AUTO = "auto"
    BOX = "box"
    SLIDER = "slider"


class NumberDeviceClass(StrEnum):
    ABSOLUTE_HUMIDITY = "absolute_humidity"
    APPARENT_POWER = "apparent_power"
    AQI = "aqi"
    AREA = "area"
    ATMOSPHERIC_PRESSURE = "atmospheric_pressure"
    BATTERY = "battery"
    BLOOD_GLUCOSE_CONCENTRATION = "blood_glucose_concentration"
    CO = "carbon_monoxide"
    CO2 = "carbon_dioxide"
    CONDUCTIVITY = "conductivity"
    CURRENT = "current"
    DATA_RATE = "data_rate"
    DATA_SIZE = "data_size"
    DISTANCE = "distance"
    DURATION = "duration"
    ENERGY = "energy"
    ENERGY_DISTANCE = "energy_distance"
    ENERGY_STORAGE = "energy_storage"
    FREQUENCY = "frequency"
    GAS = "gas"
    HUMIDITY = "humidity"
    ILLUMINANCE = "illuminance"
    IRRADIANCE = "irradiance"
    MOISTURE = "moisture"
    MONETARY = "monetary"
    NITROGEN_DIOXIDE = "nitrogen_dioxide"
    NITROGEN_MONOXIDE = "nitrogen_monoxide"
    NITROUS_OXIDE = "nitrous_oxide"
    OZONE = "ozone"
    PH = "ph"
    PM1 = "pm1"
    PM10 = "pm10"
    PM25 = "pm25"
    PM4 = "pm4"
    POWER_FACTOR = "power_factor"
    POWER = "power"
    PRECIPITATION = "precipitation"
    PRECIPITATION_INTENSITY = "precipitation_intensity"
    PRESSURE = "pressure"
    REACTIVE_ENERGY = "reactive_energy"
    REACTIVE_POWER = "reactive_power"
    SIGNAL_STRENGTH = "signal_strength"
    SOUND_PRESSURE = "sound_pressure"
    SPEED = "speed"
    SULPHUR_DIOXIDE = "sulphur_dioxide"
    TEMPERATURE = "temperature"
    TEMPERATURE_DELTA = "temperature_delta"
    VOLATILE_ORGANIC_COMPOUNDS = "volatile_organic_compounds"
    VOLATILE_ORGANIC_COMPOUNDS_PARTS = "volatile_organic_compounds_parts"
    VOLTAGE = "voltage"
    VOLUME = "volume"
    VOLUME_STORAGE = "volume_storage"
    VOLUME_FLOW_RATE = "volume_flow_rate"
    WATER = "water"
    WEIGHT = "weight"
    WIND_DIRECTION = "wind_direction"
    WIND_SPEED = "wind_speed"


class NumberAttributes(AttributesBase):
    device_class: NumberDeviceClass | None = Field(default=None)
    mode: NumberMode | None = Field(default=None)
    native_max_value: float | None = Field(default=None)
    native_min_value: float | None = Field(default=None)
    native_step: float | None = Field(default=None)
    native_unit_of_measurement: str | None = Field(default=None)
    native_value: float | None = Field(default=None)
    step: float | None = Field(default=None)
    min_value: float | None = Field(default=None)
    max_value: float | None = Field(default=None)
    unit_of_measurement: str | None = Field(default=None)


class NumberState(NumericBaseState):
    """Representation of a Home Assistant number state.

    See: https://www.home-assistant.io/integrations/number/
    """

    domain: Literal["number"]

    attributes: NumberAttributes
