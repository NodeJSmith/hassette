"""Task scheduling functionality for Home Assistant automations.

This module provides clean access to the scheduler system for running jobs
at specific times, intervals, or based on cron expressions.
"""

# TriggerProtocol is defined in hassette.types and re-exported here so that
# users discover it alongside the trigger classes rather than hunting through
# internal types packages.
from hassette.types import TriggerProtocol

from .classes import Job, ScheduleStatus, ScheduleStatusReason
from .error_context import SchedulerErrorContext
from .scheduler import Scheduler
from .sync import SchedulerSyncFacade
from .triggers import WAITING, After, Cron, Daily, EntityTime, Every, Once

__all__ = [
    "WAITING",
    "After",
    "Cron",
    "Daily",
    "EntityTime",
    "Every",
    "Job",
    "Once",
    "ScheduleStatus",
    "ScheduleStatusReason",
    "Scheduler",
    "SchedulerErrorContext",
    "SchedulerSyncFacade",
    "TriggerProtocol",
]
