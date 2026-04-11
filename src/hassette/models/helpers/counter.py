"""Pydantic models for the ``counter`` helper domain.

Models here represent the stored configuration for ``counter`` helpers, as
managed via Home Assistant's WebSocket ``counter/{list,create,update,delete}``
commands. For the live runtime value of a counter entity, use
:class:`hassette.models.states.CounterState` instead.

Note:
    ``counter`` uses HA's ``CONF_MAXIMUM``/``CONF_MINIMUM`` constants on the
    wire (``maximum``/``minimum``), not ``max``/``min`` like ``input_number``.
    This is a per-domain asymmetry verified against HA source at tag 2026.4.1.
"""

from pydantic import BaseModel, ConfigDict


class CounterRecord(BaseModel):
    """Stored ``counter`` helper configuration returned by HA.

    Related: :class:`hassette.models.states.CounterState` for the live
    runtime value.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    icon: str | None = None
    initial: int | None = None
    minimum: int | None = None
    maximum: int | None = None
    step: int | None = None
    restore: bool | None = None


class CreateCounterParams(BaseModel):
    """Parameters accepted by ``counter/create``."""

    model_config = ConfigDict(extra="forbid")

    name: str
    icon: str | None = None
    initial: int | None = None
    minimum: int | None = None
    maximum: int | None = None
    step: int | None = None
    restore: bool | None = None


class UpdateCounterParams(BaseModel):
    """Parameters accepted by ``counter/update``."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    icon: str | None = None
    initial: int | None = None
    minimum: int | None = None
    maximum: int | None = None
    step: int | None = None
    restore: bool | None = None
