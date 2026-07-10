"""Tests for src/hassette/web/utils.py — enrich_jobs_with_live_heap."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.test_utils.web_helpers import make_job_summary
from hassette.web.utils import enrich_jobs_with_live_heap


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
