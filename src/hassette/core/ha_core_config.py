"""Hassette's copy of the Home Assistant core config fields the framework reads.

Internal: ``WebsocketService`` loads it from ``get_config`` and keeps it current. Nothing on
``App``, ``Api`` or ``StateManager`` exposes it.
"""

from pydantic import BaseModel, ConfigDict

CORE_CONFIG_UPDATED_EVENT_TYPE = "core_config_updated"
"""Event Home Assistant fires when its core config (location, time zone, ...) changes at runtime."""


class HaCoreConfig(BaseModel):
    """The location and time zone Home Assistant reports in its ``get_config`` response.

    Home Assistant always reports numeric coordinates (it defaults them to ``0``), so ``0, 0`` is a
    real location, not "unset". Fields HA sends that are not declared here are ignored.
    """

    model_config = ConfigDict(frozen=True)

    latitude: float
    longitude: float
    elevation: int
    time_zone: str
