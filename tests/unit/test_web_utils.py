"""Tests for src/hassette/web/utils.py — resolve_trigger dispatch and enrich_jobs_with_live_heap."""

from typing import Literal
from unittest.mock import AsyncMock, MagicMock

import pytest
from whenever import ZonedDateTime

from hassette.scheduler.triggers import After, Daily, Every, Once
from hassette.test_utils.web_helpers import make_job_summary
from hassette.web.utils import ONE_SHOT_TRIGGER_TYPE, enrich_jobs_with_live_heap, resolve_trigger


def make_job(trigger: object | None = None) -> MagicMock:
    """Build a stub ScheduledJob with the given trigger."""
    job = MagicMock()
    job.trigger = trigger
    return job


class TestResolveTrigger:
    def test_resolve_trigger_every(self) -> None:
        job = make_job(Every(hours=1))
        assert resolve_trigger(job) == ("interval", "3600s")

    def test_resolve_trigger_daily(self) -> None:
        # Daily.trigger_detail() returns the user-written "HH:MM" (not the internal cron expression),
        # so the UI can render "Daily at 07:00" directly.
        job = make_job(Daily(at="07:00"))
        assert resolve_trigger(job) == ("cron", "07:00")

    def test_resolve_trigger_once(self) -> None:
        job = make_job(Once(at="07:00"))
        assert resolve_trigger(job) == ("once", "07:00")

    def test_resolve_trigger_after(self) -> None:
        job = make_job(After(seconds=30))
        assert resolve_trigger(job) == ("after", "30s")

    def test_resolve_trigger_no_trigger(self) -> None:
        job = make_job(trigger=None)
        assert resolve_trigger(job) == (ONE_SHOT_TRIGGER_TYPE, None)

    def test_resolve_trigger_custom(self) -> None:
        """Custom trigger implementing protocol methods — returns db_type, not label."""

        class _CustomTrigger:
            def first_run_time(self, current_time: ZonedDateTime) -> ZonedDateTime:
                return current_time

            def next_run_time(self, previous_run: ZonedDateTime, current_time: ZonedDateTime) -> ZonedDateTime:
                return current_time

            def trigger_label(self) -> str:
                return "custom"

            def trigger_detail(self) -> str | None:
                return "every 60s"

            def trigger_db_type(self) -> Literal["interval", "cron", "once", "after", "custom"]:
                return "custom"

            def trigger_id(self) -> str:
                return "custom:60"

        job = make_job(_CustomTrigger())
        assert resolve_trigger(job) == ("custom", "every 60s")


class TestEnrichJobsWithLiveHeap:
    """Unit tests for enrich_jobs_with_live_heap."""

    async def test_success_path_enriches_db_jobs(self) -> None:
        """When the snapshot succeeds, enriched rows are returned."""
        db_summary = make_job_summary(job_id=1, job_name="my_job", handler_method="MyApp.on_run")

        live_job = MagicMock()
        live_job.db_id = 1
        live_job.next_run = MagicMock()
        live_job.next_run.timestamp.return_value = 9999.0
        live_job.fire_at = None
        live_job.jitter = None
        live_job.guard.suppressed = 0
        live_job.guard.dropped = 0

        scheduler_service = MagicMock()
        scheduler_service.get_all_jobs = AsyncMock(return_value=[live_job])

        result = await enrich_jobs_with_live_heap([db_summary], scheduler_service)

        assert len(result) == 1
        assert result[0].next_run == pytest.approx(9999.0)
        scheduler_service.get_all_jobs.assert_awaited_once()

    @pytest.mark.parametrize(
        "exc",
        [OSError("disk error"), RuntimeError("heap unavailable"), ValueError("closed")],
    )
    async def test_fallback_on_snapshot_failure(self, exc: Exception) -> None:
        """When get_all_jobs() raises a snapshot error, unenriched DB rows are returned."""
        db_summary = make_job_summary(job_id=2, job_name="my_job", handler_method="MyApp.on_run")

        scheduler_service = MagicMock()
        scheduler_service.get_all_jobs = AsyncMock(side_effect=exc)

        result = await enrich_jobs_with_live_heap([db_summary], scheduler_service)

        assert result == [db_summary]
