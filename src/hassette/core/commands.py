"""Command dataclasses for the command executor."""

from dataclasses import dataclass
from typing import Any

from hassette.bus.listeners import Listener
from hassette.events.base import Event
from hassette.scheduler.classes import ScheduledJob
from hassette.types import AsyncHandlerType


@dataclass(frozen=True)
class InvokeHandler:
    """Command to invoke a listener handler for an event."""

    listener: Listener
    """The listener to invoke."""

    event: Event[Any]
    """The event to pass to the handler."""

    topic: str
    """The event topic this handler is being invoked for."""

    listener_id: int
    """FK to the listeners table; set when the listener is registered."""


@dataclass(frozen=True)
class ExecuteJob:
    """Command to execute a scheduled job."""

    job: ScheduledJob
    """The scheduled job to execute."""

    callable: AsyncHandlerType
    """The async callable to invoke."""

    job_db_id: int
    """FK to the scheduled_jobs table; set when the job is registered."""
