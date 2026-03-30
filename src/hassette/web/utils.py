"""Shared serialization helpers for the Hassette web layer."""

import asyncio
from logging import getLogger
from typing import TYPE_CHECKING

from hassette.scheduler.classes import CronTrigger, IntervalTrigger

if TYPE_CHECKING:
    from hassette.core.runtime_query_service import RuntimeQueryService
    from hassette.core.telemetry_models import ListenerSummary
    from hassette.core.telemetry_query_service import TelemetryQueryService
    from hassette.scheduler.classes import ScheduledJob

LOGGER = getLogger(__name__)


async def gather_all_listeners(
    runtime: "RuntimeQueryService",
    telemetry: "TelemetryQueryService",
    *,
    session_id: int | None = None,
) -> "list[ListenerSummary]":
    """Enumerate all app instances and gather listener summaries."""
    snapshot = runtime.get_all_manifests_snapshot()
    tasks = [
        telemetry.get_listener_summary(app_key=manifest.app_key, instance_index=instance.index, session_id=session_id)
        for manifest in snapshot.manifests
        for instance in manifest.instances
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    listeners: list[ListenerSummary] = []
    for result in results:
        if isinstance(result, BaseException):
            LOGGER.warning("Telemetry query failed gathering all listeners: %s", result)
        elif isinstance(result, list):
            listeners.extend(result)
    return listeners


def resolve_trigger(job: "ScheduledJob") -> tuple[str, str | None]:
    """Return (trigger_type, trigger_detail) for a ScheduledJob.

    Returns:
        A tuple of (trigger_type, trigger_detail) where trigger_type is one of
        "interval", "cron", or "one-shot", and trigger_detail is a human-readable
        description (e.g. "every 30s", "*/5 * * * *", or None for one-shot jobs).
    """
    trigger = job.trigger
    if isinstance(trigger, IntervalTrigger):
        return "interval", f"every {trigger.interval}"
    if isinstance(trigger, CronTrigger):
        return "cron", str(trigger.cron_expression)
    return "one-shot", None
