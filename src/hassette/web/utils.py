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


def resolve_trigger(job: "ScheduledJob") -> tuple[str, str | None]:
    """Return (trigger_db_type, trigger_detail) for a ScheduledJob.

    Delegates to ``TriggerProtocol.trigger_db_type()`` and ``trigger_detail()``.
    ``trigger_db_type()`` is the stable DB discriminator — not the display label.
    Custom triggers show as ``"custom"`` in REST; consumers needing the human label
    should inspect ``trigger_detail``.

    The protocol invariant is enforced at ``Scheduler.schedule()`` via an
    ``isinstance(trigger, TriggerProtocol)`` check that raises ``TypeError``
    synchronously, so ``job.trigger`` is guaranteed to either be ``None`` or a
    protocol-conformant instance when this function is called.

    Returns:
        A tuple of (db_type, detail) where db_type is the trigger's DB discriminator
        (e.g. "interval", "cron", "once", "after", "custom") and detail is an
        optional human-readable description (e.g. "3600s", "07:00"), or
        ``("one-shot", None)`` when the job has no trigger.
    """
    trigger = job.trigger
    if trigger is None:
        return "one-shot", None
    return trigger.trigger_db_type(), trigger.trigger_detail()
