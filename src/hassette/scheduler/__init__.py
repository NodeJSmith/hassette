"""Task scheduling functionality for Home Assistant automations.

This module provides clean access to the scheduler system for running jobs
at specific times, intervals, or based on cron expressions.
"""

# TriggerProtocol is defined in hassette.types and re-exported here so that
# users discover it alongside the trigger classes rather than hunting through
# internal types packages.
from hassette.types import TriggerProtocol

from .classes import ScheduledJob
from .scheduler import Scheduler
from .triggers import After, Cron, Daily, Every, Once

__all__ = [
    "After",
    "Cron",
    "Daily",
    "Every",
    "Once",
    "ScheduledJob",
    "Scheduler",
    "TriggerProtocol",
]
