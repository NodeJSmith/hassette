"""Pydantic models for the ``input_select`` helper domain.

Models here represent the stored configuration for ``input_select`` helpers,
as managed via Home Assistant's WebSocket ``input_select/{list,create,update,delete}``
commands. For the live runtime state of an ``input_select`` entity, use
:class:`hassette.models.states.InputSelectState` instead.
"""

from pydantic import BaseModel, ConfigDict


class InputSelectRecord(BaseModel):
    """Stored ``input_select`` helper configuration returned by HA."""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    options: list[str]
    initial: str | None = None
    icon: str | None = None


class CreateInputSelectParams(BaseModel):
    """Parameters accepted by ``input_select/create``."""

    model_config = ConfigDict(extra="forbid")

    name: str
    options: list[str]
    initial: str | None = None
    icon: str | None = None


class UpdateInputSelectParams(BaseModel):
    """Parameters accepted by ``input_select/update``."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    options: list[str] | None = None
    initial: str | None = None
    icon: str | None = None
