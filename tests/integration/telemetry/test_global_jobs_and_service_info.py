"""Tests for global jobs endpoint and ServiceInfoResponse extension.

Covers:
- get_job_summary() returns jobs from multiple apps when app_key is None
- GET /api/scheduler/jobs enriches with live heap data when available
- GET /api/scheduler/jobs returns DB-only data on scheduler failure (degraded)
- ServiceInfoResponse includes role, ready_phase, retry_at when available
"""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from hassette.core.database_service import DatabaseService
from hassette.core.runtime_query_service import RuntimeQueryService
from hassette.core.telemetry.query_service import TelemetryQueryService
from hassette.exceptions import TelemetryUnavailableError
from hassette.scheduler.triggers import Every
from hassette.schemas.domain_models import ServiceInfo, SystemStatus
from hassette.schemas.telemetry_models import JobSummary
from hassette.test_utils.web_helpers import make_job_summary, make_real_job
from hassette.test_utils.web_mocks import create_hassette_stub, create_mock_runtime_query_service
from hassette.types.enums import ResourceRole, ResourceStatus
from hassette.web.app import create_fastapi_app
from hassette.web.mappers import system_status_response_from
from hassette.web.models import ServiceInfoResponse

from .helpers import (
    insert_execution,
    insert_job,
)

STUB_TIMESTAMP = 1_700_000_000.0


class TestGetJobSummaryGlobal:
    async def test_returns_jobs_from_multiple_apps(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """get_job_summary() aggregates jobs from multiple apps without app_key filter."""
        db_svc, session_id = db

        j1 = await insert_job(db_svc, app_key="app_alpha", job_name="alpha_job")
        j2 = await insert_job(db_svc, app_key="app_beta", job_name="beta_job")

        await insert_execution(db_svc, j1, session_id, status="success", duration_ms=10.0)
        await insert_execution(db_svc, j2, session_id, status="error", duration_ms=50.0, error_type="ValueError")

        results = await query_service.get_job_summary()

        assert len(results) == 2
        app_keys = {r.app_key for r in results}
        assert app_keys == {"app_alpha", "app_beta"}
        assert all(isinstance(r, JobSummary) for r in results)

    async def test_no_app_key_filter_returns_all(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """All jobs are returned regardless of app_key when no filter is applied."""
        db_svc, _ = db

        for i in range(5):
            await insert_job(db_svc, app_key=f"app_{i}", job_name=f"job_{i}")

        results = await query_service.get_job_summary()
        assert len(results) == 5

    async def test_includes_error_fields(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Jobs with failed executions have last_error_type, last_error_message populated."""
        db_svc, session_id = db

        j1 = await insert_job(db_svc, app_key="my_app", job_name="failing_job")
        await insert_execution(
            db_svc,
            j1,
            session_id,
            status="error",
            duration_ms=5.0,
            error_type="RuntimeError",
            error_message="something went wrong",
        )

        results = await query_service.get_job_summary()
        assert len(results) == 1
        row = results[0]
        assert row.last_error_type == "RuntimeError"
        assert row.last_error_message == "something went wrong"

    async def test_includes_min_max_duration(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """min_duration_ms and max_duration_ms are populated from executions."""
        db_svc, session_id = db

        j1 = await insert_job(db_svc, app_key="my_app", job_name="timed_job")
        await insert_execution(db_svc, j1, session_id, status="success", duration_ms=5.0)
        await insert_execution(db_svc, j1, session_id, status="success", duration_ms=100.0)
        await insert_execution(db_svc, j1, session_id, status="success", duration_ms=50.0)

        results = await query_service.get_job_summary()
        assert len(results) == 1
        row = results[0]
        assert row.min_duration_ms == pytest.approx(5.0)
        assert row.max_duration_ms == pytest.approx(100.0)

    async def test_no_executions_has_none_min_max(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Jobs with no executions have min/max duration as None (never executed)."""
        db_svc, _ = db

        await insert_job(db_svc, app_key="my_app", job_name="idle_job")

        results = await query_service.get_job_summary()
        assert len(results) == 1
        row = results[0]
        assert row.min_duration_ms is None
        assert row.max_duration_ms is None

    async def test_since_filter_restricts_by_timestamp(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """since parameter filters executions by timestamp."""
        db_svc, session_id = db

        base_ts = 1_000_000.0
        since_ts = base_ts + 5.0

        j1 = await insert_job(db_svc, app_key="my_app", job_name="my_job")
        # Before since: counts should not include this
        await insert_execution(db_svc, j1, session_id, status="success", execution_start_ts=base_ts + 1.0)
        # After since: should count
        await insert_execution(db_svc, j1, session_id, status="success", execution_start_ts=base_ts + 10.0)

        results = await query_service.get_job_summary(since=since_ts)
        assert len(results) == 1
        row = results[0]
        assert row.total_executions == 1

    async def test_source_tier_app_excludes_framework(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """source_tier='app' excludes framework-tier jobs."""
        db_svc, _ = db

        await insert_job(db_svc, app_key="my_app", job_name="app_job", source_tier="app")
        await insert_job(db_svc, app_key="fw_app", job_name="fw_job", source_tier="framework")

        results = await query_service.get_job_summary(source_tier="app")
        assert len(results) == 1
        assert results[0].source_tier == "app"

    async def test_source_tier_all_includes_both_tiers(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """source_tier='all' returns both app and framework tier jobs."""
        db_svc, _ = db

        await insert_job(db_svc, app_key="my_app", job_name="app_job", source_tier="app")
        await insert_job(db_svc, app_key="fw_app", job_name="fw_job", source_tier="framework")

        results = await query_service.get_job_summary(source_tier="all")
        assert len(results) == 2

    async def test_last_error_row_coherence(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Multiple errors — all last_error_* columns come from the most recent error row."""
        db_svc, session_id = db
        base_ts = 1_000_000.0

        j1 = await insert_job(db_svc, app_key="coh_app", job_name="coherent_job")
        await insert_execution(
            db_svc,
            j1,
            session_id,
            status="error",
            error_type="OldError",
            error_message="old message",
            error_traceback="old traceback",
            execution_start_ts=base_ts + 1.0,
        )
        await insert_execution(
            db_svc,
            j1,
            session_id,
            status="error",
            error_type="NewError",
            error_message="new message",
            error_traceback="new traceback",
            execution_start_ts=base_ts + 10.0,
        )

        results = await query_service.get_job_summary()
        assert len(results) == 1
        row = results[0]
        # All three error columns must come from the same (most recent) row
        assert row.last_error_type == "NewError"
        assert row.last_error_message == "new message"
        assert row.last_error_traceback == "new traceback"
        assert row.last_error_ts == pytest.approx(base_ts + 10.0)

    async def test_since_filter_scopes_error_cte(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Error before the since window is excluded from last_error_* in get_job_summary."""
        db_svc, session_id = db
        base_ts = 1_000_000.0
        since_ts = base_ts + 50.0

        j1 = await insert_job(db_svc, app_key="my_app", job_name="windowed_job")
        await insert_execution(
            db_svc,
            j1,
            session_id,
            status="error",
            error_type="OldError",
            error_message="before window",
            error_traceback="old tb",
            execution_start_ts=base_ts + 1.0,
        )
        await insert_execution(
            db_svc,
            j1,
            session_id,
            status="error",
            error_type="NewError",
            error_message="inside window",
            error_traceback="new tb",
            execution_start_ts=base_ts + 100.0,
        )

        results = await query_service.get_job_summary(since=since_ts)
        assert len(results) == 1
        row = results[0]
        assert row.last_error_type == "NewError"
        assert row.last_error_message == "inside window"
        assert row.last_error_traceback == "new tb"


@pytest.fixture
def mock_hassette_scheduler():
    """Create a mock Hassette stub for global scheduler tests."""
    return create_hassette_stub(run_web_ui=False)


@pytest.fixture
async def scheduler_client(mock_hassette_scheduler):
    """AsyncClient wired to the scheduler test app."""
    app = create_fastapi_app(mock_hassette_scheduler)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestGlobalJobsEndpointExists:
    async def test_endpoint_returns_200(self, scheduler_client, mock_hassette_scheduler) -> None:
        """GET /api/scheduler/jobs returns 200 and a list."""
        mock_hassette_scheduler.telemetry_query_service.get_job_summary = AsyncMock(return_value=[])
        mock_hassette_scheduler.scheduler_service.get_all_jobs = AsyncMock(return_value=[])

        response = await scheduler_client.get("/api/scheduler/jobs")
        assert response.status_code == 200
        assert response.json() == []


class TestGlobalJobsEndpointMultipleApps:
    async def test_returns_jobs_from_multiple_apps(self, scheduler_client, mock_hassette_scheduler) -> None:
        """GET /api/scheduler/jobs returns jobs from multiple apps."""
        db_jobs = [
            make_job_summary(job_id=1, app_key="app_alpha", next_run=None),
            make_job_summary(job_id=2, app_key="app_beta", next_run=None),
        ]
        mock_hassette_scheduler.telemetry_query_service.get_job_summary = AsyncMock(return_value=db_jobs)
        mock_hassette_scheduler.scheduler_service.get_all_jobs = AsyncMock(return_value=[])

        response = await scheduler_client.get("/api/scheduler/jobs")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        app_keys = {row["app_key"] for row in data}
        assert app_keys == {"app_alpha", "app_beta"}


class TestGlobalJobsEndpointEnrichesWithLiveData:
    async def test_enriches_with_live_heap_data(self, scheduler_client, mock_hassette_scheduler) -> None:
        """Global jobs endpoint enriches DB rows with live next_run, fire_at, jitter."""
        db_summary = make_job_summary(job_id=42, app_key="my_app", next_run=None)
        mock_hassette_scheduler.telemetry_query_service.get_job_summary = AsyncMock(return_value=[db_summary])

        trigger = Every(hours=1)
        live_job = make_real_job(name="test_job", trigger=trigger, jitter=10.0)
        live_job.mark_registered(42)
        live_job.fire_at = live_job.next_run.add(seconds=5.0)
        mock_hassette_scheduler.scheduler_service.get_all_jobs = AsyncMock(return_value=[live_job])

        response = await scheduler_client.get("/api/scheduler/jobs")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        row = data[0]

        assert row["next_run"] is not None
        assert isinstance(row["next_run"], float)
        assert row["jitter"] == 10.0
        assert row["fire_at"] is not None


class TestGlobalJobsEndpointDegradedOnHeapFailure:
    async def test_returns_db_rows_when_heap_unavailable(self, scheduler_client, mock_hassette_scheduler) -> None:
        """Returns DB-only rows (no 500) when get_all_jobs() raises."""
        db_summary = make_job_summary(job_id=55, next_run=None)
        mock_hassette_scheduler.telemetry_query_service.get_job_summary = AsyncMock(return_value=[db_summary])
        mock_hassette_scheduler.scheduler_service.get_all_jobs = AsyncMock(side_effect=RuntimeError("heap unavailable"))

        response = await scheduler_client.get("/api/scheduler/jobs")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["next_run"] is None
        assert data[0]["fire_at"] is None

    async def test_db_error_returns_503(self, scheduler_client, mock_hassette_scheduler) -> None:
        """TelemetryUnavailableError returns 503 response."""
        mock_hassette_scheduler.telemetry_query_service.get_job_summary = AsyncMock(
            side_effect=TelemetryUnavailableError("disk I/O error")
        )

        response = await scheduler_client.get("/api/scheduler/jobs")
        assert response.status_code == 503
        assert response.json() == []


class TestServiceInfoResponseExtension:
    def test_service_info_response_has_role_ready_phase_retry_at(self) -> None:
        """ServiceInfoResponse has role, ready_phase, retry_at fields."""
        resp = ServiceInfoResponse(
            name="WebSocketService",
            status="running",
            role="Service",
            ready_phase="connected",
            retry_at=STUB_TIMESTAMP,
        )
        assert resp.role == "Service"
        assert resp.ready_phase == "connected"
        assert resp.retry_at == STUB_TIMESTAMP

    def test_service_info_response_defaults(self) -> None:
        """ServiceInfoResponse has sensible defaults when role/ready_phase/retry_at omitted."""
        resp = ServiceInfoResponse(name="SomeService", status="running")
        assert resp.role == ""
        assert resp.ready_phase is None
        assert resp.retry_at is None

    def test_system_status_response_from_mapper_populates_fields(self) -> None:
        """system_status_response_from() populates role, ready_phase, retry_at from ServiceInfo."""
        status = SystemStatus(
            status="ok",
            websocket_connected=True,
            uptime_seconds=60.0,
            entity_count=5,
            app_count=2,
            services_running=["WebSocketService"],
            services=[
                ServiceInfo(
                    name="WebSocketService",
                    status="running",
                    role="Service",
                    ready_phase="connected",
                    retry_at=None,
                ),
                ServiceInfo(
                    name="DatabaseService",
                    status="exhausted_cooling",
                    role="Service",
                    ready_phase=None,
                    retry_at=1700001000.0,
                ),
            ],
        )

        response = system_status_response_from(status)

        ws_svc = next(s for s in response.services if s.name == "WebSocketService")
        assert ws_svc.role == "Service"
        assert ws_svc.ready_phase == "connected"
        assert ws_svc.retry_at is None

        db_svc = next(s for s in response.services if s.name == "DatabaseService")
        assert db_svc.retry_at == 1700001000.0
        assert db_svc.ready_phase is None

    def test_get_system_status_populates_service_info_fields(self) -> None:
        """get_system_status() populates role, ready_phase, retry_at on ServiceInfo objects."""
        mock_child = MagicMock()
        mock_child.class_name = "WebSocketService"
        mock_child.status = ResourceStatus.RUNNING
        mock_child.role = ResourceRole.SERVICE
        mock_child._ready_reason = "connected to HA"
        mock_child._retry_at = None

        mock_hs = MagicMock()
        mock_hs.websocket_service = mock_child
        mock_hs.websocket_service.is_ready.return_value = True
        mock_hs._websocket_service = mock_child
        mock_hs.state_proxy.states = {}
        mock_hs.state_proxy.is_ready.return_value = True
        mock_hs.children = [mock_child]
        mock_hs.app_handler.registry.get_full_snapshot.return_value = MagicMock(manifests=[])
        mock_hs.app_handler.get_status_snapshot.return_value = MagicMock(total_count=0)

        svc_instance = RuntimeQueryService.__new__(RuntimeQueryService)
        svc_instance.hassette = mock_hs
        svc_instance._start_time = time.time() - 10
        svc_instance.logger = MagicMock()

        result = svc_instance.get_system_status()

        assert len(result.services) == 1
        svc_info = result.services[0]
        assert svc_info.name == "WebSocketService"
        assert svc_info.role == "Service"


class TestHealthEndpointServiceInfoFields:
    async def test_health_endpoint_returns_services_with_role(self, scheduler_client, mock_hassette_scheduler) -> None:
        """GET /api/health returns services array with role field populated."""
        mock_child = MagicMock()
        mock_child.class_name = "WebSocketService"
        mock_child.status = ResourceStatus.RUNNING
        mock_child.role = ResourceRole.SERVICE
        mock_child._ready_reason = "connected"
        mock_child._retry_at = None

        mock_hassette_scheduler.children = [mock_child]

        # Wire runtime_query_service so it uses a real get_system_status
        rqs = create_mock_runtime_query_service(mock_hassette_scheduler)
        mock_hassette_scheduler.runtime_query_service = rqs

        response = await scheduler_client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "services" in data
        # Each service entry should have a role field
        for service in data["services"]:
            assert "role" in service
