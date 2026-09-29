"""Tests for src/hassette/web/utils.py — enrich_jobs_with_live and enrich_jobs_with_live_data."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.web.utils import enrich_jobs_with_live, enrich_jobs_with_live_data
from tests.support.web_job_helpers import make_job_summary


class TestEnrichJobsWithLiveData:
    """Unit tests for enrich_jobs_with_live_data."""

    async def test_success_path_enriches_db_jobs(self) -> None:
        """When the snapshot succeeds, enriched rows are returned."""
        db_summary = make_job_summary(job_id=1, job_name="my_job", handler_method="MyApp.on_run")

        live_job = MagicMock()
        live_job.db_id = 1
        live_job.next_run = MagicMock()
        live_job.next_run.timestamp.return_value = 9999.0
        live_job.fire_at = None
        live_job.jitter = None
        live_job.schedule_status.value = "scheduled"
        live_job.schedule_status_reason = None
        live_job.guard.suppressed = 0
        live_job.guard.dropped = 0

        scheduler_service = MagicMock()
        scheduler_service.get_all_jobs = AsyncMock(return_value=[live_job])

        result = await enrich_jobs_with_live_data([db_summary], scheduler_service)

        assert len(result) == 1
        assert result[0].next_run == pytest.approx(9999.0)
        assert result[0].schedule_status == "scheduled"
        assert result[0].schedule_status_reason is None
        scheduler_service.get_all_jobs.assert_awaited_once()

    @pytest.mark.parametrize(
        "exc",
        [OSError("disk error"), RuntimeError("registry unavailable"), ValueError("closed")],
    )
    async def test_fallback_on_snapshot_failure(self, exc: Exception) -> None:
        """When get_all_jobs() raises a snapshot error, unenriched DB rows are returned."""
        db_summary = make_job_summary(job_id=2, job_name="my_job", handler_method="MyApp.on_run")

        scheduler_service = MagicMock()
        scheduler_service.get_all_jobs = AsyncMock(side_effect=exc)

        result = await enrich_jobs_with_live_data([db_summary], scheduler_service)

        assert result == [db_summary]


class TestEnrichJobsWithLive:
    """Unit tests for enrich_jobs_with_live — called directly, not through the async wrapper."""

    def test_wrong_typed_live_value_falls_back_to_db_row(self) -> None:
        """A live job whose overlaid value has the wrong type leaves that job's DB row unmodified.

        Other jobs in the same call are still enriched — the fallback is per-job, not batch-wide.
        """
        broken_summary = make_job_summary(job_id=1, job_name="broken_job")
        healthy_summary = make_job_summary(job_id=2, job_name="healthy_job")

        broken_live = MagicMock()
        broken_live.db_id = 1
        broken_live.next_run = None
        broken_live.fire_at = None
        broken_live.jitter = object()  # wrong type for the float | None field
        broken_live.schedule_status.value = "scheduled"
        broken_live.schedule_status_reason = None
        broken_live.guard.suppressed = 0
        broken_live.guard.dropped = 0

        healthy_live = MagicMock()
        healthy_live.db_id = 2
        healthy_live.next_run = None
        healthy_live.fire_at = None
        healthy_live.jitter = None
        healthy_live.schedule_status.value = "waiting"
        healthy_live.schedule_status_reason = None
        healthy_live.guard.suppressed = 1
        healthy_live.guard.dropped = 0

        result = enrich_jobs_with_live([broken_summary, healthy_summary], [broken_live, healthy_live])

        assert result[0] is broken_summary
        assert result[1] is not healthy_summary
        assert result[1].schedule_status == "waiting"
        assert result[1].suppressed_count == 1
