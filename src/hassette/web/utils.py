"""Shared serialization helpers for the Hassette web layer."""

import asyncio
from logging import getLogger
from typing import TYPE_CHECKING

from hassette.core.telemetry_models import JobSummary

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
    since: float | None = None,
) -> "list[ListenerSummary]":
    """Enumerate all app instances and gather listener summaries.

    Returns listeners of all source tiers (app and framework) by default.
    Callers that need tier filtering should filter on the ``source_tier`` field
    of the returned ``ListenerSummary`` objects.
    """
    snapshot = runtime.get_all_manifests_snapshot()
    tasks = [
        telemetry.get_listener_summary(
            app_key=manifest.app_key, instance_index=instance.index, since=since, source_tier="all"
        )
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


def enrich_jobs_with_heap(
    db_jobs: list[JobSummary],
    live_jobs: "list[ScheduledJob]",
) -> list[JobSummary]:
    """Enrich DB job summaries with live scheduler heap data.

    Matches DB rows to live heap entries by ``db_id``. For each match, copies
    ``next_run``, ``fire_at``, ``jitter``, and ``cancelled`` from the live state.
    Jobs without a live match are returned unmodified.
    """
    live_by_db_id = {job.db_id: job for job in live_jobs if job.db_id is not None}

    enriched: list[JobSummary] = []
    for js in db_jobs:
        try:
            live_job = live_by_db_id.get(js.job_id)
            if live_job is not None:
                is_cancelled = js.cancelled
                if is_cancelled:
                    next_run_ts = None
                    fire_at_ts = None
                else:
                    next_run_ts = live_job.next_run.timestamp()
                    fire_at_ts = live_job.fire_at.timestamp() if live_job.jitter is not None else None

                enriched.append(
                    js.model_copy(
                        update={
                            "next_run": next_run_ts,
                            "fire_at": fire_at_ts,
                            "jitter": live_job.jitter,
                            "cancelled": is_cancelled,
                        }
                    )
                )
            else:
                enriched.append(js)
        except (AttributeError, TypeError, ValueError):
            LOGGER.warning("Failed to enrich job summary for job_id=%s; using DB row", js.job_id, exc_info=True)
            enriched.append(js)
    return enriched


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
