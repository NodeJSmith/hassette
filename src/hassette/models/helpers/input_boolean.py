"""Pydantic models for the ``input_boolean`` helper domain.

Models here represent the stored configuration for ``input_boolean`` helpers,
as managed via Home Assistant's WebSocket ``input_boolean/{list,create,update,delete}``
commands. For the live runtime state of an ``input_boolean`` entity, use
:class:`hassette.models.states.InputBooleanState` instead.
"""

from pydantic import BaseModel, ConfigDict


class InputBooleanRecord(BaseModel):
    """Stored ``input_boolean`` helper configuration returned by HA."""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    icon: str | None = None
    initial: bool | None = None


class CreateInputBooleanParams(BaseModel):
    """Parameters accepted by ``input_boolean/create``."""

    model_config = ConfigDict(extra="forbid")

    name: str
    icon: str | None = None
    initial: bool | None = None


class UpdateInputBooleanParams(BaseModel):
    """Parameters accepted by ``input_boolean/update``."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    icon: str | None = None
    initial: bool | None = None
