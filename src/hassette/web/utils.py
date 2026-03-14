"""Shared serialization helpers for the Hassette web layer."""

from typing import TYPE_CHECKING

from hassette.scheduler.classes import CronTrigger, IntervalTrigger

if TYPE_CHECKING:
    from hassette.scheduler.classes import ScheduledJob


def resolve_trigger(job: "ScheduledJob") -> tuple[str, str | None]:
    """Return (trigger_type, trigger_detail) for a ScheduledJob.

    Returns:
        A tuple of (trigger_type, trigger_detail) where trigger_type is one of
        "interval", "cron", or "once". trigger_detail is None for once-triggers,
        the interval duration string for interval triggers, and the cron
        expression string for cron triggers.
    """
    trigger = job.trigger
    if isinstance(trigger, IntervalTrigger):
        return "interval", str(trigger.interval)
    if isinstance(trigger, CronTrigger):
        return "cron", str(trigger.cron_expression)
    return "once", None
