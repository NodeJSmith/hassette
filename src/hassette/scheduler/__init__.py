"""Task scheduling functionality for Home Assistant automations.

This module provides clean access to the scheduler system for running jobs
at specific times, intervals, or based on cron expressions.
"""

# TriggerProtocol is defined in hassette.types and re-exported here so that
# users discover it alongside the trigger classes rather than hunting through
# internal types packages.
from hassette.types import TriggerProtocol

from .classes import CronTrigger, IntervalTrigger, ScheduledJob
from .scheduler import Scheduler
from .triggers import After, Cron, Daily, Every, Once

__all__ = [
    "After",
    "Cron",
    "CronTrigger",
    "Daily",
    "Every",
    "IntervalTrigger",
    "Once",
    "ScheduledJob",
    "Scheduler",
    "TriggerProtocol",
]
