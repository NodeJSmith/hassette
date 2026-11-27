# dup-ignore-file: HA helper models — Record/Create/Update classes share fields by API design
"""Pydantic models for the ``input_number`` helper domain.

Models here represent the stored configuration for ``input_number`` helpers,
as managed via Home Assistant's WebSocket ``input_number/{list,create,update,delete}``
commands. For the live runtime state of an ``input_number`` entity, use
:class:`hassette.models.states.InputNumberState` instead.

Note:
    HA's server-side schema enforces ``max > min`` and
    ``min <= initial <= max``. Hassette does not mirror this invariant on
    ``Create*Params`` / ``Update*Params``: an update only carries the fields
    it changes, so HA checks the record it merges them into. Errors surface
    from HA via :class:`hassette.exceptions.CommandRejectedError`.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class InputNumberRecord(BaseModel):
    """Stored ``input_number`` helper configuration returned by HA.

    Fields HA fills in when a helper is stored default to HA's own values, so a record built
    without them (by the test harness, say) matches what HA would return.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    min: float
    max: float
    initial: float | None = None
    step: float = 1
    icon: str | None = None
    unit_of_measurement: str | None = None
    mode: Literal["box", "slider"] = "slider"


class CreateInputNumberParams(BaseModel):
    """Parameters accepted by ``input_number/create``."""

    model_config = ConfigDict(extra="forbid")

    name: str
    min: float
    max: float
    initial: float | None = None
    step: float | None = None
    icon: str | None = None
    unit_of_measurement: str | None = None
    mode: Literal["box", "slider"] | None = None


class UpdateInputNumberParams(BaseModel):
    """Parameters accepted by ``input_number/update``.

    Note:
        HA requires ``min`` and ``max``, so passing ``None`` for either (which
        clears it) is rejected.
    """

    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    min: float | None = None
    max: float | None = None
    initial: float | None = None
    step: float | None = None
    icon: str | None = None
    unit_of_measurement: str | None = None
    mode: Literal["box", "slider"] | None = None
