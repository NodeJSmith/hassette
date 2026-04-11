"""Pydantic models for the ``input_datetime`` helper domain.

Models here represent the stored configuration for ``input_datetime`` helpers,
as managed via Home Assistant's WebSocket ``input_datetime/{list,create,update,delete}``
commands. For the live runtime state of an ``input_datetime`` entity, use
:class:`hassette.models.states.InputDatetimeState` instead.
"""

from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator


class InputDatetimeRecord(BaseModel):
    """Stored ``input_datetime`` helper configuration returned by HA."""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    has_date: bool = False
    has_time: bool = False
    icon: str | None = None
    initial: str | None = None


class CreateInputDatetimeParams(BaseModel):
    """Parameters accepted by ``input_datetime/create``.

    Enforces HA's ``has_date or has_time`` invariant locally so the error
    surfaces with a Pydantic ``ValidationError`` rather than a generic HA
    failure response.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    has_date: bool = False
    has_time: bool = False
    icon: str | None = None
    initial: str | None = None

    @model_validator(mode="after")
    def _require_date_or_time(self) -> Self:
        if not (self.has_date or self.has_time):
            raise ValueError("input_datetime helper must have at least one of 'has_date' or 'has_time' set to True")
        return self


class UpdateInputDatetimeParams(BaseModel):
    """Parameters accepted by ``input_datetime/update``.

    The ``has_date``/``has_time`` invariant is **not** enforced on update
    because partial updates only carry fields the caller changed — validating
    them in isolation would reject legitimate updates that leave the other
    flag at its stored value. HA validates the merged state server-side.
    """

    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    has_date: bool | None = None
    has_time: bool | None = None
    icon: str | None = None
    initial: str | None = None
