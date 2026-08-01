"""Shared serialization helpers for the Hassette web layer."""

from logging import getLogger
from typing import TYPE_CHECKING

from hassette.schemas.job_models import JobSummary

if TYPE_CHECKING:
    from hassette.core.scheduler_service import SchedulerService
    from hassette.scheduler.classes import Job

LOGGER = getLogger(__name__)


def enrich_jobs_with_live(
    db_jobs: list[JobSummary],
    live_jobs: "list[Job]",
) -> list[JobSummary]:
    """Enrich DB job summaries with live scheduler registry data.

    Matches DB rows to live registry entries (``SchedulerService._jobs_by_id``, not the
    due-time heap) by ``db_id``, so scheduled, waiting, completed, and manual jobs are all
    joinable — not just heap-resident ones.

    For each match, overlays ``schedule_status`` and ``schedule_status_reason`` from the live
    ``Job`` state, plus ``suppressed_count``/``dropped_count`` read from the entry's guard.
    Timing (``next_run``, ``fire_at``, ``jitter``) is copied only when the live job carries a
    concrete automatic occurrence (``SCHEDULED`` status) — waiting, completed, and manual jobs
    always overlay null timing, since only a ``SCHEDULED`` job's ``next_run``/``fire_at`` are
    ever non-``None`` (see ``Job.transition_to``/``set_next_run``).

    Jobs without a live match are returned unmodified — the DB row's own persisted
    ``schedule_status``/``schedule_status_reason``/timing stay authoritative (counts keep
    their ``JobSummary`` defaults of ``0``, indistinguishable from "no overlap events").
    """
    live_by_db_id = {job.db_id: job for job in live_jobs if job.db_id is not None}

    enriched: list[JobSummary] = []
    for js in db_jobs:
        live_job = live_by_db_id.get(js.job_id)
        if live_job is None:
            enriched.append(js)
            continue
        try:
            guard = live_job.guard
            enriched.append(
                js.model_copy(
                    update={
                        "schedule_status": live_job.schedule_status.value,
                        "schedule_status_reason": (
                            live_job.schedule_status_reason.value
                            if live_job.schedule_status_reason is not None
                            else None
                        ),
                        "next_run": live_job.next_run.timestamp() if live_job.next_run is not None else None,
                        "fire_at": live_job.fire_at.timestamp()
                        if live_job.jitter is not None and live_job.fire_at is not None
                        else None,
                        "jitter": live_job.jitter,
                        "suppressed_count": guard.suppressed,
                        "dropped_count": guard.dropped,
                    }
                )
            )
        except (AttributeError, TypeError, ValueError):
            LOGGER.warning("Failed to enrich job summary for job_id=%s; using DB row", js.job_id, exc_info=True)
            enriched.append(js)
    return enriched


async def enrich_jobs_with_live_data(
    db_jobs: list[JobSummary],
    scheduler_service: "SchedulerService",
    context: str = "enrichment",
) -> list[JobSummary]:
    """Enrich DB job rows with live registry data, falling back to DB rows on snapshot failure.

    ``context`` labels the warning log so a failed snapshot can be traced to its call site
    (e.g. ``"global enrichment"`` vs ``"enrichment"``).

    On failure, persisted ``schedule_status``/``schedule_status_reason`` remain available
    (sourced from the DB row) but timing is explicitly unavailable and therefore null —
    ``get_all_jobs()`` returns a list copy with no lock held during enrichment.
    """
    try:
        live_jobs = await scheduler_service.get_all_jobs()
    except (OSError, RuntimeError, ValueError):
        LOGGER.warning("Failed to fetch live scheduler jobs for %s; returning DB rows only", context, exc_info=True)
        return db_jobs
    return enrich_jobs_with_live(db_jobs, live_jobs)
