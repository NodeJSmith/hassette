"""Shared serialization helpers for the Hassette web layer."""

import asyncio
import logging
from typing import TYPE_CHECKING

from hassette.scheduler.classes import CronTrigger, IntervalTrigger

if TYPE_CHECKING:
    from hassette.core.runtime_query_service import RuntimeQueryService
    from hassette.core.telemetry_query_service import TelemetryQueryService
    from hassette.scheduler.classes import ScheduledJob

logger = logging.getLogger(__name__)


async def gather_all_listeners(
    runtime: "RuntimeQueryService",
    telemetry: "TelemetryQueryService",
) -> list[dict]:
    """Enumerate all app instances and gather listener summaries."""
    snapshot = runtime.get_all_manifests_snapshot()
    tasks = [
        telemetry.get_listener_summary(app_key=manifest.app_key, instance_index=instance.index)
        for manifest in snapshot.manifests
        for instance in manifest.instances
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    listeners: list[dict] = []
    for result in results:
        if isinstance(result, BaseException):
            logger.warning("Telemetry query failed gathering all listeners: %s", result)
        elif isinstance(result, list):
            listeners.extend(result)
    return listeners


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
