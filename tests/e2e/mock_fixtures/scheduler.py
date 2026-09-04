"""Scheduler job builders and trigger wiring for e2e mock data."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from tests.e2e.mock_fixtures.constants import APP_KEY_MY_APP
from tests.support.web_job_helpers import make_job


def build_scheduler_jobs() -> list[SimpleNamespace]:
    """Build scheduler job stubs for e2e seed data."""
    return [
        make_job(trigger_detail="PT30S", app_key=APP_KEY_MY_APP, instance_index=0),
        make_job(
            job_id="job-2",
            name="morning_routine",
            next_run="2024-01-01T07:00:00",
            trigger_type="cron",
            trigger_detail="0 7 * * * 0",
            app_key=APP_KEY_MY_APP,
            instance_index=0,
        ),
    ]


def wire_scheduler_trigger(hassette, job_names_by_id: dict[int, str]) -> None:
    """Wire ``POST /api/scheduler/jobs/{id}/trigger`` to succeed for known job ids.

    ``SchedulerService.trigger_job()``/``submit_job()`` normally resolve against the live
    registry (``_jobs_by_id``); this stub bypasses that and just returns a minimal live-job
    stand-in so the route's ``job.name`` access and 202 response construction succeed. Used by
    e2e tests that click "Run Now" — a job id not present in
    ``job_names_by_id`` raises, mirroring the real 409 "no live registration" outcome.
    """

    async def _trigger_job(job_id: int):
        name = job_names_by_id.get(job_id)
        if name is None:
            raise ValueError(f"No live registration for job_id={job_id}")
        return SimpleNamespace(name=name, db_id=job_id)

    hassette._scheduler_service.trigger_job = AsyncMock(side_effect=_trigger_job)
    hassette._scheduler_service.submit_job = MagicMock()
