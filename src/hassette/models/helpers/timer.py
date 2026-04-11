"""Pydantic models for the ``timer`` helper domain.

Models here represent the stored configuration for ``timer`` helpers, as
managed via Home Assistant's WebSocket ``timer/{list,create,update,delete}``
commands. For the live runtime state of a timer entity, use
:class:`hassette.models.states.TimerState` instead.

Note:
    ``timer.duration`` is a ``timedelta`` server-side. Hassette accepts
    either the canonical string format ``"HH:MM:SS"`` or an integer number
    of seconds, and forwards the value to HA's ``cv.time_period`` coercion.
    Timer service actions (``timer.start``/``pause``/``cancel``) are
    registered as entity services, not WebSocket commands — use
    :meth:`hassette.api.Api.call_service` for them.
"""

from pydantic import BaseModel, ConfigDict


class TimerRecord(BaseModel):
    """Stored ``timer`` helper configuration returned by HA."""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    icon: str | None = None
    duration: str | int | None = None
    restore: bool | None = None


class CreateTimerParams(BaseModel):
    """Parameters accepted by ``timer/create``.

    ``duration`` accepts a ``"HH:MM:SS"`` string or an integer number of
    seconds.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    icon: str | None = None
    duration: str | int | None = None
    restore: bool | None = None


class UpdateTimerParams(BaseModel):
    """Parameters accepted by ``timer/update``."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    icon: str | None = None
    duration: str | int | None = None
    restore: bool | None = None
