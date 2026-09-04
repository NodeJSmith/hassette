"""Integration tests for telemetry route enrichment.

Tests verify:
- app_jobs enriches DB rows with live heap data when a live match exists
- app_jobs leaves live fields None when no live match exists
- app_jobs returns DB rows without enrichment when get_all_jobs() raises (graceful degradation)
"""

from collections.abc import Sequence
from unittest.mock import AsyncMock

import pytest
from httpx2 import AsyncClient

from hassette.scheduler.classes import Job
from hassette.scheduler.triggers import Every
from hassette.schemas.job_models import JobSummary
from hassette.types.enums import ExecutionMode
from tests.support.web_job_helpers import make_job_summary, make_real_job

from .conftest import get_json

APP_JOBS_PATH = "/api/telemetry/app/my_app/jobs"
GLOBAL_JOBS_PATH = "/api/scheduler/jobs"

HOURLY = Every(hours=1)
"""Shared recurring trigger — no test here cares about the interval value itself."""


def make_live_job(db_id: int, name: str, **kwargs) -> Job:  # factory-local: stamps db_id via mark_registered
    """Build a real heap job already registered under `db_id`, as the live scheduler would hold it.

    `make_real_job(db_id=...)` sets the field directly; this goes through `mark_registered()` so
    the job passes through the same registration path the enrichment lookup matches on.
    """
    job = make_real_job(name=name, trigger=HOURLY, **kwargs)
    job.mark_registered(db_id)
    return job


async def get_enriched_job_row(
    client: AsyncClient,
    mock_hassette,
    *,
    db_summary: JobSummary,
    live_jobs: Sequence[Job] = (),
    path: str = APP_JOBS_PATH,
) -> dict:
    """Wire one DB job summary plus the live heap contents, then return the single response row.

    Every enrichment test here drives the same shape: one persisted row, zero or one matching
    live job, one GET, one row back.
    """
    mock_hassette.telemetry_query_service.get_job_summary = AsyncMock(return_value=[db_summary])
    mock_hassette.scheduler_service.get_all_jobs = AsyncMock(return_value=list(live_jobs))

    rows = await get_json(client, path)

    assert len(rows) == 1
    return rows[0]


class TestAppJobsEnrichmentWithLiveMatch:
    """When a live heap job matches by db_id, enriched fields are populated."""

    async def test_next_run_fire_at_jitter_from_live(self, client: AsyncClient, mock_hassette) -> None:
        live_job = make_live_job(42, "test_job", jitter=15.0)
        # fire_at deliberately differs from next_run (jitter is applied at enqueue time by the service).
        live_job.fire_at = live_job.next_run.add(seconds=10.0)

        row = await get_enriched_job_row(
            client,
            mock_hassette,
            db_summary=make_job_summary(job_id=42, job_name="test_job", group="morning", next_run=None),
            live_jobs=[live_job],
        )

        # next_run and fire_at arrive as epoch floats, taken from the live job.
        assert row["next_run"] == pytest.approx(live_job.next_run.timestamp(), abs=0.01)
        assert isinstance(row["next_run"], float)
        # fire_at is populated because the live job carries a concrete fire_at value.
        assert row["fire_at"] == pytest.approx(live_job.fire_at.timestamp(), abs=0.01)
        assert isinstance(row["fire_at"], float)
        assert row["jitter"] == 15.0

    async def test_next_run_fire_at_no_jitter_from_live(self, client: AsyncClient, mock_hassette) -> None:
        """fire_at is populated even when the job has no jitter — it should equal next_run."""
        live_job = make_live_job(43, "test_job_no_jitter")

        row = await get_enriched_job_row(
            client,
            mock_hassette,
            db_summary=make_job_summary(job_id=43, job_name="test_job_no_jitter", group="morning", next_run=None),
            live_jobs=[live_job],
        )

        assert live_job.jitter is None
        assert row["next_run"] == pytest.approx(live_job.next_run.timestamp(), abs=0.01)
        assert row["fire_at"] == pytest.approx(live_job.fire_at.timestamp(), abs=0.01)
        assert row["fire_at"] == pytest.approx(row["next_run"], abs=0.01)
        assert row["jitter"] is None


class TestAppJobsEnrichmentNoLiveMatch:
    """When no live heap job matches by db_id, live fields are None."""

    async def test_no_live_match_live_fields_none(self, client: AsyncClient, mock_hassette) -> None:
        row = await get_enriched_job_row(
            client,
            mock_hassette,
            db_summary=make_job_summary(job_id=99, job_name="test_job", group="morning", next_run=None),
        )

        assert row["next_run"] is None
        assert row["fire_at"] is None
        assert row["jitter"] is None


class TestAppJobsEnrichmentHeapFailureDegrades:
    """When get_all_jobs() raises, DB rows are returned without enrichment (no 500)."""

    async def test_heap_failure_returns_db_rows_status_200(self, client: AsyncClient, mock_hassette) -> None:
        db_summary = make_job_summary(job_id=55, job_name="test_job", group="morning", next_run=None)
        mock_hassette.telemetry_query_service.get_job_summary = AsyncMock(return_value=[db_summary])
        mock_hassette.scheduler_service.get_all_jobs = AsyncMock(side_effect=RuntimeError("heap unavailable"))

        rows = await get_json(client, APP_JOBS_PATH)

        # Must not 500 — returns the DB row with no live enrichment.
        assert len(rows) == 1
        assert rows[0]["next_run"] is None
        assert rows[0]["fire_at"] is None
        assert rows[0]["jitter"] is None


class TestAppJobsModeAndLiveCounts:
    """mode and suppressed/dropped counts surface correctly from the live heap."""

    async def test_mode_from_db_flows_through_to_response(self, client: AsyncClient, mock_hassette) -> None:
        """Mode from DB row appears in the API response."""
        db_summary = make_job_summary(job_id=10, job_name="queued_job").model_copy(
            update={"mode": ExecutionMode.QUEUED}
        )

        row = await get_enriched_job_row(client, mock_hassette, db_summary=db_summary)

        assert row["mode"] == "queued"
        assert row["suppressed_count"] == 0
        assert row["dropped_count"] == 0

    async def test_live_suppressed_and_dropped_from_guard(self, client: AsyncClient, mock_hassette) -> None:
        """suppressed_count and dropped_count are read from the live job's guard."""
        live_job = make_live_job(20, "single_job")
        live_job.guard.suppressed = 5
        live_job.guard.dropped = 2

        row = await get_enriched_job_row(
            client,
            mock_hassette,
            db_summary=make_job_summary(job_id=20, job_name="single_job"),
            live_jobs=[live_job],
        )

        assert row["suppressed_count"] == 5
        assert row["dropped_count"] == 2

    async def test_fresh_job_no_guard_activity_reports_zero_counts(self, client: AsyncClient, mock_hassette) -> None:
        """A job with no guard activity reports (0, 0) for suppressed/dropped counts."""
        row = await get_enriched_job_row(
            client,
            mock_hassette,
            db_summary=make_job_summary(job_id=30, job_name="fresh_job"),
            live_jobs=[make_live_job(30, "fresh_job")],  # guard starts at (0, 0)
        )

        assert row["suppressed_count"] == 0
        assert row["dropped_count"] == 0

    async def test_no_live_match_counts_default_to_zero(self, client: AsyncClient, mock_hassette) -> None:
        """When a job has no live heap entry, suppressed/dropped default to 0."""
        row = await get_enriched_job_row(
            client, mock_hassette, db_summary=make_job_summary(job_id=40, job_name="offline_job")
        )

        assert row["suppressed_count"] == 0
        assert row["dropped_count"] == 0

    async def test_global_jobs_route_returns_mode_and_counts(self, client: AsyncClient, mock_hassette) -> None:
        """GET /api/scheduler/jobs also surfaces mode and live counts."""
        db_summary = make_job_summary(job_id=50, job_name="global_job").model_copy(
            update={"mode": ExecutionMode.RESTART}
        )
        live_job = make_live_job(50, "global_job")
        live_job.guard.suppressed = 3
        live_job.guard.dropped = 0

        row = await get_enriched_job_row(
            client, mock_hassette, db_summary=db_summary, live_jobs=[live_job], path=GLOBAL_JOBS_PATH
        )

        assert row["mode"] == "restart"
        assert row["suppressed_count"] == 3
        assert row["dropped_count"] == 0
