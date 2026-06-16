"""Shared serialization helpers for the Hassette web layer."""

from logging import getLogger
from typing import TYPE_CHECKING

from hassette.core.telemetry_models import JobSummary

if TYPE_CHECKING:
    from hassette.scheduler.classes import ScheduledJob

ONE_SHOT_TRIGGER_TYPE = "one-shot"

LOGGER = getLogger(__name__)


def enrich_jobs_with_heap(
    db_jobs: list[JobSummary],
    live_jobs: "list[ScheduledJob]",
) -> list[JobSummary]:
    """Enrich DB job summaries with live scheduler heap data.

    Matches DB rows to live heap entries by ``db_id``. For each match, copies
    ``next_run``, ``fire_at``, and ``jitter`` from the live state, plus the live
    ``suppressed_count``/``dropped_count`` read from the heap entry's guard.
    Jobs without a live match are returned unmodified (counts keep their
    ``JobSummary`` defaults of ``0`` — indistinguishable from "no overlap events").
    """
    live_by_db_id = {job.db_id: job for job in live_jobs if job.db_id is not None}

    enriched: list[JobSummary] = []
    for js in db_jobs:
        try:
            live_job = live_by_db_id.get(js.job_id)
            if live_job is not None:
                guard = live_job.guard
                enriched.append(
                    js.model_copy(
                        update={
                            "next_run": live_job.next_run.timestamp(),
                            "fire_at": live_job.fire_at.timestamp() if live_job.jitter is not None else None,
                            "jitter": live_job.jitter,
                            "suppressed_count": guard.suppressed,
                            "dropped_count": guard.dropped,
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
        return ONE_SHOT_TRIGGER_TYPE, None
    return trigger.trigger_db_type(), trigger.trigger_detail()
