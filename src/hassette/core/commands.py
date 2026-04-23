"""Command dataclasses for the command executor."""

import typing
from dataclasses import dataclass
from typing import Any

from hassette.bus.listeners import Listener
from hassette.events.base import Event
from hassette.scheduler.classes import ScheduledJob
from hassette.types import AsyncHandlerType, SourceTier

if typing.TYPE_CHECKING:
    from hassette.types.types import BusErrorHandlerType, SchedulerErrorHandlerType


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

    app_level_error_handler: "BusErrorHandlerType | None" = None
    """App-level error handler resolved at dispatch time from Bus._error_handler.

    Populated by BusService._make_tracked_invoke_fn() as a fallback when the listener
    has no per-registration error handler. None when the Bus has no app-level handler set.
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

    app_level_error_handler: "SchedulerErrorHandlerType | None" = None
    """App-level error handler resolved at dispatch time from Scheduler._error_handler.

    Populated by SchedulerService.run_job() as a fallback when the job has no
    per-registration error handler. None when the Scheduler has no app-level handler set.
    """
