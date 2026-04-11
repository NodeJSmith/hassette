"""Pydantic models for the ``input_text`` helper domain.

Models here represent the stored configuration for ``input_text`` helpers,
as managed via Home Assistant's WebSocket ``input_text/{list,create,update,delete}``
commands. For the live runtime state of an ``input_text`` entity, use
:class:`hassette.models.states.InputTextState` instead.

Note:
    HA's server-side schema enforces ``min <= max`` and validates that
    ``initial`` fits the length bounds. Hassette does not mirror this
    invariant on ``Create*Params`` / ``Update*Params``; errors surface from
    HA via :class:`hassette.exceptions.FailedMessageError`.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class InputTextRecord(BaseModel):
    """Stored ``input_text`` helper configuration returned by HA."""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    min: int | None = None
    max: int | None = None
    initial: str | None = None
    icon: str | None = None
    unit_of_measurement: str | None = None
    pattern: str | None = None
    mode: Literal["text", "password"] | None = None


class CreateInputTextParams(BaseModel):
    """Parameters accepted by ``input_text/create``."""

    model_config = ConfigDict(extra="forbid")

    name: str
    min: int | None = None
    max: int | None = None
    initial: str | None = None
    icon: str | None = None
    unit_of_measurement: str | None = None
    pattern: str | None = None
    mode: Literal["text", "password"] | None = None


class UpdateInputTextParams(BaseModel):
    """Parameters accepted by ``input_text/update``."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    min: int | None = None
    max: int | None = None
    initial: str | None = None
    icon: str | None = None
    unit_of_measurement: str | None = None
    pattern: str | None = None
    mode: Literal["text", "password"] | None = None
