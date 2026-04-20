"""Command dataclasses for the command executor."""

from dataclasses import dataclass
from typing import Any

from hassette.bus.listeners import Listener
from hassette.events.base import Event
from hassette.scheduler.classes import ScheduledJob
from hassette.types import AsyncHandlerType, SourceTier


@dataclass(frozen=True)
class InvokeHandler:
    """Command to invoke a listener handler for an event."""

    listener: Listener
    """The listener to invoke."""

    event: Event[Any]
    """The event to pass to the handler."""

    topic: str
    """The event topic this handler is being invoked for."""

    listener_id: int | None
    """FK to the listeners table; None when the listener hasn't been registered yet."""

    source_tier: SourceTier
    """Whether this invocation originates from a user app or the framework itself.

    Required (no default) to prevent silent miscategorization.
    """

    effective_timeout: float | None
    """Per-execution timeout in seconds, or None for no timeout.

    Required (no default) to prevent silent omission at construction sites.
    ``None`` means no deadline is enforced (``asyncio.timeout(None)`` is a no-op).
    """


@dataclass(frozen=True)
class ExecuteJob:
    """Command to execute a scheduled job."""

    job: ScheduledJob
    """The scheduled job to execute."""

    callable: AsyncHandlerType
    """The async callable to invoke."""

    job_db_id: int | None
    """FK to the scheduled_jobs table; None when the job hasn't been registered yet."""

    source_tier: SourceTier
    """Whether this execution originates from a user app or the framework itself.

    Required (no default) to prevent silent miscategorization.
    """

    effective_timeout: float | None
    """Per-execution timeout in seconds, or None for no timeout.

    Required (no default) to prevent silent omission at construction sites.
    ``None`` means no deadline is enforced (``asyncio.timeout(None)`` is a no-op).
    """
