"""Pydantic models for the ``input_boolean`` helper domain.

Models here represent the stored configuration for ``input_boolean`` helpers,
as managed via Home Assistant's WebSocket ``input_boolean/{list,create,update,delete}``
commands. For the live runtime state of an ``input_boolean`` entity, use
:class:`hassette.models.states.InputBooleanState` instead.
"""

from pydantic import BaseModel, ConfigDict


class InputBooleanRecord(BaseModel):
    """Stored ``input_boolean`` helper configuration returned by HA.

    Uses ``extra="allow"`` so unknown fields added by future HA releases pass
    through without raising ``ValidationError``.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    icon: str | None = None
    initial: bool | None = None


class CreateInputBooleanParams(BaseModel):
    """Parameters accepted by ``input_boolean/create``.

    Use ``model_dump(exclude_unset=True)`` when serializing so untouched
    optional fields are omitted from the WebSocket payload and HA applies its
    own defaults.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    icon: str | None = None
    initial: bool | None = None


class UpdateInputBooleanParams(BaseModel):
    """Parameters accepted by ``input_boolean/update``.

    Uses ``extra="ignore"`` so round-tripping a Record (which may carry HA
    fields Hassette does not yet model) through an update call does not raise.
    """

    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    icon: str | None = None
    initial: bool | None = None
