"""Integration tests for the telemetry route enrichment (WP02, spec 2039).

Tests verify:
- app_jobs enriches DB rows with live heap data when a live match exists
- app_jobs leaves live fields None when no live match exists (but keeps DB cancelled)
- app_jobs returns DB rows without enrichment when get_all_jobs() raises (graceful degradation)
"""

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from hassette.core.telemetry_models import JobSummary
from hassette.scheduler.triggers import Every
from hassette.test_utils.web_helpers import make_real_job
from hassette.test_utils.web_mocks import create_hassette_stub
from hassette.web.app import create_fastapi_app


@pytest.fixture
def mock_hassette_enrichment():
    """Create a mock Hassette stub suitable for enrichment tests."""
    return create_hassette_stub(run_web_ui=False)


@pytest.fixture
async def enrichment_client(mock_hassette_enrichment):
    """AsyncClient wired to the enrichment-test app."""
    app = create_fastapi_app(mock_hassette_enrichment)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, mock_hassette_enrichment


def _make_job_summary(
    job_id: int = 1,
    app_key: str = "my_app",
    job_name: str = "test_job",
    cancelled_at_set: bool = False,
) -> JobSummary:
    """Build a JobSummary as would be returned by get_job_summary()."""
    return JobSummary(
        job_id=job_id,
        app_key=app_key,
        instance_index=0,
        job_name=job_name,
        handler_method="MyApp.on_run",
        trigger_type="interval",
        trigger_label="every 1h",
        trigger_detail=None,
        args_json="[]",
        kwargs_json="{}",
        source_location="my_app.py:10",
        registration_source=None,
        total_executions=5,
        successful=5,
        failed=0,
        last_executed_at=1700000000.0,
        total_duration_ms=100.0,
        avg_duration_ms=20.0,
        group="morning",
        cancelled=cancelled_at_set,  # reflects DB cancelled_at IS NOT NULL
    )


class TestAppJobsEnrichmentWithLiveMatch:
    """When a live heap job matches by db_id, enriched fields are populated."""

    async def test_next_run_fire_at_jitter_cancelled_from_live(self, enrichment_client) -> None:
        client, mock_hassette = enrichment_client

        # Arrange: one DB job summary
        db_summary = _make_job_summary(job_id=42)
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
        assert row["next_run"] == pytest.approx(live_job.next_run.timestamp(), abs=1.0)

        # fire_at is populated because jitter is not None
        assert row["fire_at"] is not None
        assert isinstance(row["fire_at"], float)
        assert row["fire_at"] == pytest.approx(live_job.fire_at.timestamp(), abs=1.0)

        # jitter is set
        assert row["jitter"] == 15.0

        # cancelled comes from live job (not cancelled)
        assert row["cancelled"] is False


class TestAppJobsEnrichmentNoLiveMatch:
    """When no live heap job matches by db_id, live fields are None, cancelled from DB."""

    async def test_no_live_match_live_fields_none(self, enrichment_client) -> None:
        client, mock_hassette = enrichment_client

        # Arrange: DB job with cancelled_at IS NOT NULL (cancelled=True in DB)
        db_summary = _make_job_summary(job_id=99, cancelled_at_set=True)
        mock_hassette.telemetry_query_service.get_job_summary = AsyncMock(return_value=[db_summary])

        # Arrange: live jobs list is empty (no match)
        mock_hassette.scheduler_service.get_all_jobs = AsyncMock(return_value=[])

        # Act
        response = await client.get("/api/telemetry/app/my_app/jobs")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        row = data[0]

        # No live match — live fields are None
        assert row["next_run"] is None
        assert row["fire_at"] is None
        assert row["jitter"] is None

        # cancelled comes from DB (cancelled_at IS NOT NULL → cancelled=True)
        assert row["cancelled"] is True

    async def test_no_live_match_uncancelled_db_row(self, enrichment_client) -> None:
        client, mock_hassette = enrichment_client

        # Arrange: DB job with cancelled_at IS NULL (cancelled=False in DB)
        db_summary = _make_job_summary(job_id=77, cancelled_at_set=False)
        mock_hassette.telemetry_query_service.get_job_summary = AsyncMock(return_value=[db_summary])
        mock_hassette.scheduler_service.get_all_jobs = AsyncMock(return_value=[])

        response = await client.get("/api/telemetry/app/my_app/jobs")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        row = data[0]

        assert row["next_run"] is None
        assert row["cancelled"] is False


class TestAppJobsEnrichmentHeapFailureDegrades:
    """When get_all_jobs() raises, DB rows are returned without enrichment (no 500)."""

    async def test_heap_failure_returns_db_rows_status_200(self, enrichment_client) -> None:
        client, mock_hassette = enrichment_client

        # Arrange: DB job
        db_summary = _make_job_summary(job_id=55)
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

    async def test_heap_failure_does_not_500(self, enrichment_client) -> None:
        """Verify response is not 500 regardless of exception type."""
        client, mock_hassette = enrichment_client

        mock_hassette.telemetry_query_service.get_job_summary = AsyncMock(return_value=[_make_job_summary(job_id=1)])
        mock_hassette.scheduler_service.get_all_jobs = AsyncMock(side_effect=Exception("unexpected error"))

        response = await client.get("/api/telemetry/app/my_app/jobs")
        assert response.status_code == 200
