"""Shared serialization helpers for the Hassette web layer."""

import asyncio
from logging import getLogger
from typing import TYPE_CHECKING

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


def resolve_trigger(job: "ScheduledJob") -> tuple[str | None, str | None]:
    """Return (trigger_type, trigger_detail) for a ScheduledJob.

    Delegates to ``TriggerProtocol.trigger_db_type()`` and
    ``trigger_detail()`` — no isinstance dispatch.  Falls back to
    ``str(trigger)`` for legacy trigger objects that do not implement
    the protocol.

    Returns:
        A tuple of (type, detail) where type is the trigger's DB discriminator
        (e.g. "interval", "cron", "once", "after", "custom") and detail is an
        optional human-readable description (e.g. "3600s", "0 7 * * *"), or
        ``(None, None)`` when the job has no trigger.
    """
    trigger = job.trigger
    if trigger is None:
        return None, None
    if hasattr(trigger, "trigger_db_type"):
        return trigger.trigger_db_type(), trigger.trigger_detail()
    # Legacy IntervalTrigger/CronTrigger: __str__ returns "type:detail".
    text = str(trigger)
    type_str, sep, detail = text.partition(":")
    if not sep:
        LOGGER.warning("Trigger %r has no ':' separator in str() — using full string as type", trigger)
    return type_str, detail or None
