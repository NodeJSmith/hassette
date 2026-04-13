"""Pydantic models for the ``input_button`` helper domain.

Models here represent the stored configuration for ``input_button`` helpers,
as managed via Home Assistant's WebSocket ``input_button/{list,create,update,delete}``
commands. For the live runtime state of an ``input_button`` entity, use
:class:`hassette.models.states.InputButtonState` instead.

Note:
    ``input_button`` is press-to-trigger — there is no ``initial`` value or
    stored state. The press action is a service call
    (``input_button.press``), not a WebSocket command.
"""

from pydantic import BaseModel, ConfigDict


class InputButtonRecord(BaseModel):
    """Stored ``input_button`` helper configuration returned by HA."""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    icon: str | None = None


class CreateInputButtonParams(BaseModel):
    """Parameters accepted by ``input_button/create``."""

    model_config = ConfigDict(extra="forbid")

    name: str
    icon: str | None = None


class UpdateInputButtonParams(BaseModel):
    """Parameters accepted by ``input_button/update``."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    icon: str | None = None
