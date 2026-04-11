"""Pydantic models for the ``input_number`` helper domain.

Models here represent the stored configuration for ``input_number`` helpers,
as managed via Home Assistant's WebSocket ``input_number/{list,create,update,delete}``
commands. For the live runtime state of an ``input_number`` entity, use
:class:`hassette.models.states.InputNumberState` instead.

Note:
    HA's server-side schema enforces ``max > min`` and
    ``min <= initial <= max``. Hassette does not mirror this invariant on
    ``Create*Params`` / ``Update*Params`` — partial updates make the check
    context-dependent (it must merge with existing stored state). Errors
    surface from HA via :class:`hassette.exceptions.FailedMessageError`.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class InputNumberRecord(BaseModel):
    """Stored ``input_number`` helper configuration returned by HA."""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    min: float
    max: float
    initial: float | None = None
    step: float | None = None
    icon: str | None = None
    unit_of_measurement: str | None = None
    mode: Literal["box", "slider"] | None = None


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

    Note: HA requires ``min``/``max`` to be valid floats when set — passing
    explicit ``None`` for these fields is not a valid operation. The harness
    does not enforce this constraint; production HA will reject the request
    server-side.
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
