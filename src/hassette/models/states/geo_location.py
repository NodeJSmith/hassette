from typing import Literal

from pydantic import Field

from .base import AttributesBase, NumericBaseState


class GeoLocationAttributes(AttributesBase):
    source: str | None = Field(default=None)
    distance: float | None = Field(default=None)
    latitude: float | None = Field(default=None)
    longitude: float | None = Field(default=None)


class GeoLocationState(NumericBaseState):
    """Representation of a Home Assistant geo_location state.

    See: https://www.home-assistant.io/integrations/geo_location/
    """

    domain: Literal["geo_location"]

    attributes: GeoLocationAttributes
