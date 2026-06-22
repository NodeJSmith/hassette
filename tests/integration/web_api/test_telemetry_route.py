"""Integration tests for telemetry route enrichment.

Tests verify:
- app_jobs enriches DB rows with live heap data when a live match exists
- app_jobs leaves live fields None when no live match exists
- app_jobs returns DB rows without enrichment when get_all_jobs() raises (graceful degradation)
"""

from unittest.mock import AsyncMock

import pytest

from hassette.scheduler.triggers import Every
from hassette.test_utils.web_helpers import make_job_summary, make_real_job


class TestAppJobsEnrichmentWithLiveMatch:
    """When a live heap job matches by db_id, enriched fields are populated."""

    async def test_next_run_fire_at_jitter_from_live(self, client, mock_hassette) -> None:
        # Arrange: one DB job summary
        db_summary = make_job_summary(
            job_id=42, job_name="test_job", handler_method="MyApp.on_run", group="morning", next_run=None
        )
        mock_hassette.telemetry_query_service.get_job_summary = AsyncMock(return_value=[db_summary])

        # Arrange: matching live job with db_id=42
        trigger = Every(hours=1)
        live_job = make_real_job(name="test_job", trigger=trigger, jitter=15.0)
        live_job.mark_registered(42)  # set db_id to 42
        # Manually set fire_at to differ from next_run (jitter applied at enqueue time by service)
        live_job.fire_at = live_job.next_run.add(seconds=10.0)

        mock_hassette.scheduler_service.get_all_jobs = AsyncMock(return_value=[live_job])

        # Act
        response = await client.get("/api/telemetry/app/my_app/jobs")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        row = data[0]

        # next_run should be epoch float
        assert row["next_run"] is not None
        assert isinstance(row["next_run"], float)
        assert row["next_run"] == pytest.approx(live_job.next_run.timestamp(), abs=0.01)

        # fire_at is populated because jitter is not None
        assert row["fire_at"] is not None
        assert isinstance(row["fire_at"], float)
        assert row["fire_at"] == pytest.approx(live_job.fire_at.timestamp(), abs=0.01)

        # jitter is set
        assert row["jitter"] == 15.0


class TestAppJobsEnrichmentNoLiveMatch:
    """When no live heap job matches by db_id, live fields are None."""

    async def test_no_live_match_live_fields_none(self, client, mock_hassette) -> None:
        db_summary = make_job_summary(
            job_id=99, job_name="test_job", handler_method="MyApp.on_run", group="morning", next_run=None
        )
        mock_hassette.telemetry_query_service.get_job_summary = AsyncMock(return_value=[db_summary])
        mock_hassette.scheduler_service.get_all_jobs = AsyncMock(return_value=[])

        response = await client.get("/api/telemetry/app/my_app/jobs")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        row = data[0]

        assert row["next_run"] is None
        assert row["fire_at"] is None
        assert row["jitter"] is None


class TestAppJobsEnrichmentHeapFailureDegrades:
    """When get_all_jobs() raises, DB rows are returned without enrichment (no 500)."""

    async def test_heap_failure_returns_db_rows_status_200(self, client, mock_hassette) -> None:
        # Arrange: DB job
        db_summary = make_job_summary(
            job_id=55, job_name="test_job", handler_method="MyApp.on_run", group="morning", next_run=None
        )
        mock_hassette.telemetry_query_service.get_job_summary = AsyncMock(return_value=[db_summary])

        # Arrange: get_all_jobs raises
        mock_hassette.scheduler_service.get_all_jobs = AsyncMock(side_effect=RuntimeError("heap unavailable"))

        # Act
        response = await client.get("/api/telemetry/app/my_app/jobs")

        # Must not 500 — returns DB rows without live enrichment
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1

        # No live enrichment
        row = data[0]
        assert row["next_run"] is None
        assert row["fire_at"] is None
        assert row["jitter"] is None


class TestAppJobsModeAndLiveCounts:
    """mode and suppressed/dropped counts surface correctly from the live heap."""

    async def test_mode_from_db_flows_through_to_response(self, client, mock_hassette) -> None:
        """mode from DB row appears in the API response."""
        db_summary = make_job_summary(job_id=10, job_name="queued_job", handler_method="MyApp.on_run")
        # Simulate DB row having mode='queued' via model_copy
        db_summary = db_summary.model_copy(update={"mode": "queued"})
        mock_hassette.telemetry_query_service.get_job_summary = AsyncMock(return_value=[db_summary])
        mock_hassette.scheduler_service.get_all_jobs = AsyncMock(return_value=[])

        response = await client.get("/api/telemetry/app/my_app/jobs")

        assert response.status_code == 200
        row = response.json()[0]
        assert row["mode"] == "queued"
        assert row["suppressed_count"] == 0
        assert row["dropped_count"] == 0

    async def test_live_suppressed_and_dropped_from_guard(self, client, mock_hassette) -> None:
        """suppressed_count and dropped_count are read from the live job's guard."""
        db_summary = make_job_summary(job_id=20, job_name="single_job", handler_method="MyApp.on_run")
        mock_hassette.telemetry_query_service.get_job_summary = AsyncMock(return_value=[db_summary])

        # Build a real job with db_id=20 and simulate guard activity
        trigger = Every(hours=1)
        live_job = make_real_job(name="single_job", trigger=trigger)
        live_job.mark_registered(20)
        # Manually set guard counters to simulate prior suppression
        live_job.guard.suppressed = 5
        live_job.guard.dropped = 2

        mock_hassette.scheduler_service.get_all_jobs = AsyncMock(return_value=[live_job])

        response = await client.get("/api/telemetry/app/my_app/jobs")

        assert response.status_code == 200
        row = response.json()[0]
        assert row["suppressed_count"] == 5
        assert row["dropped_count"] == 2

    async def test_fresh_job_no_guard_activity_reports_zero_counts(self, client, mock_hassette) -> None:
        """A job with no guard activity reports (0, 0) for suppressed/dropped counts."""
        db_summary = make_job_summary(job_id=30, job_name="fresh_job", handler_method="MyApp.on_run")
        mock_hassette.telemetry_query_service.get_job_summary = AsyncMock(return_value=[db_summary])

        trigger = Every(hours=1)
        live_job = make_real_job(name="fresh_job", trigger=trigger)
        live_job.mark_registered(30)
        # guard starts at (0, 0) by default

        mock_hassette.scheduler_service.get_all_jobs = AsyncMock(return_value=[live_job])

        response = await client.get("/api/telemetry/app/my_app/jobs")

        assert response.status_code == 200
        row = response.json()[0]
        assert row["suppressed_count"] == 0
        assert row["dropped_count"] == 0

    async def test_no_live_match_counts_default_to_zero(self, client, mock_hassette) -> None:
        """When a job has no live heap entry, suppressed/dropped default to 0."""
        db_summary = make_job_summary(job_id=40, job_name="offline_job", handler_method="MyApp.on_run")
        mock_hassette.telemetry_query_service.get_job_summary = AsyncMock(return_value=[db_summary])
        mock_hassette.scheduler_service.get_all_jobs = AsyncMock(return_value=[])

        response = await client.get("/api/telemetry/app/my_app/jobs")

        assert response.status_code == 200
        row = response.json()[0]
        assert row["suppressed_count"] == 0
        assert row["dropped_count"] == 0

    async def test_global_jobs_route_returns_mode_and_counts(self, client, mock_hassette) -> None:
        """GET /api/scheduler/jobs also surfaces mode and live counts."""
        db_summary = make_job_summary(job_id=50, job_name="global_job", handler_method="MyApp.on_run")
        db_summary = db_summary.model_copy(update={"mode": "restart"})
        mock_hassette.telemetry_query_service.get_job_summary = AsyncMock(return_value=[db_summary])

        trigger = Every(hours=1)
        live_job = make_real_job(name="global_job", trigger=trigger)
        live_job.mark_registered(50)
        live_job.guard.suppressed = 3
        live_job.guard.dropped = 0

        mock_hassette.scheduler_service.get_all_jobs = AsyncMock(return_value=[live_job])

        response = await client.get("/api/scheduler/jobs")

        assert response.status_code == 200
        row = response.json()[0]
        assert row["mode"] == "restart"
        assert row["suppressed_count"] == 3
        assert row["dropped_count"] == 0
