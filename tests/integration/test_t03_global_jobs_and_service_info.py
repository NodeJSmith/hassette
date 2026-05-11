"""Tests for T03: global jobs endpoint, gather_all_listeners tier fix, ServiceInfoResponse extension.

Covers:
- get_all_jobs_summary() returns jobs from multiple apps, no app_key filter
- GET /api/scheduler/jobs enriches with live heap data when available
- GET /api/scheduler/jobs returns DB-only data on scheduler failure (degraded)
- gather_all_listeners() returns both app and framework tiers
- ServiceInfoResponse includes role, ready_phase, retry_at when available
"""

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from hassette.core.database_service import DatabaseService
from hassette.core.domain_models import ServiceInfo, SystemStatus
from hassette.core.runtime_query_service import RuntimeQueryService
from hassette.core.telemetry_models import JobSummary, ListenerSummary
from hassette.core.telemetry_query_service import TelemetryQueryService
from hassette.scheduler.triggers import Every
from hassette.test_utils.web_helpers import make_real_job
from hassette.test_utils.web_mocks import create_hassette_stub, create_mock_runtime_query_service
from hassette.types.enums import ResourceRole, ResourceStatus
from hassette.web.app import create_fastapi_app
from hassette.web.mappers import system_status_response_from
from hassette.web.utils import gather_all_listeners

# ---------------------------------------------------------------------------
# Fixtures: real DB for TelemetryQueryService tests
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_hassette_db(tmp_path: Path) -> MagicMock:
    hassette = MagicMock()
    hassette.config.data_dir = tmp_path
    hassette.config.db_path = None
    hassette.config.db_retention_days = 7
    hassette.config.telemetry_write_queue_max = 500
    hassette.config.db_write_queue_max = 2000
    hassette.config.database_service_log_level = "INFO"
    hassette.config.log_level = "INFO"
    hassette.config.task_bucket_log_level = "INFO"
    hassette.config.resource_shutdown_timeout_seconds = 5
    hassette.config.task_cancellation_timeout_seconds = 5
    hassette.config.web_api_log_level = "INFO"
    hassette.config.run_web_api = True
    hassette.config.db_migration_timeout_seconds = 120
    hassette.config.db_max_size_mb = 0
    hassette.ready_event = asyncio.Event()
    return hassette


@pytest.fixture
async def db(mock_hassette_db: MagicMock) -> AsyncIterator[tuple[DatabaseService, int]]:
    db_service = DatabaseService(mock_hassette_db, parent=mock_hassette_db)
    await db_service.on_initialize()
    cursor = await db_service.db.execute(
        "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
        (time.time(), time.time()),
    )
    session_id = cursor.lastrowid
    await db_service.db.commit()
    mock_hassette_db.session_id = session_id
    mock_hassette_db.database_service = db_service
    yield db_service, session_id
    await db_service.on_shutdown()


@pytest.fixture
def svc(mock_hassette_db: MagicMock, db: tuple[DatabaseService, int]) -> TelemetryQueryService:  # noqa: ARG001
    service = TelemetryQueryService.__new__(TelemetryQueryService)
    service.hassette = mock_hassette_db
    service.logger = MagicMock()
    service._snapshot_lock = asyncio.Lock()
    return service


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _insert_job(
    db_svc: DatabaseService,
    *,
    app_key: str = "test_app",
    instance_index: int = 0,
    job_name: str = "my_job",
    handler_method: str = "run_job",
    source_tier: str = "app",
) -> int:
    cursor = await db_svc.db.execute(
        """INSERT INTO scheduled_jobs
               (app_key, instance_index, job_name, handler_method,
                trigger_type, repeat,
                source_location, source_tier)
           VALUES (?, ?, ?, ?, 'interval', 1, 'test.py:1', ?)""",
        (app_key, instance_index, job_name, handler_method, source_tier),
    )
    await db_svc.db.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


async def _insert_execution(
    db_svc: DatabaseService,
    job_id: int,
    session_id: int,
    *,
    status: str = "success",
    duration_ms: float = 20.0,
    error_type: str | None = None,
    error_message: str | None = None,
    execution_start_ts: float | None = None,
    source_tier: str = "app",
) -> int:
    ts = execution_start_ts if execution_start_ts is not None else time.time()
    cursor = await db_svc.db.execute(
        """INSERT INTO job_executions
               (job_id, session_id, execution_start_ts, duration_ms,
                status, error_type, error_message, source_tier, is_di_failure)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)""",
        (job_id, session_id, ts, duration_ms, status, error_type, error_message, source_tier),
    )
    await db_svc.db.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


async def _insert_listener(
    db_svc: DatabaseService,
    *,
    app_key: str = "test_app",
    instance_index: int = 0,
    handler_method: str = "on_event",
    topic: str = "hass.event.state_changed",
    source_tier: str = "app",
) -> int:
    cursor = await db_svc.db.execute(
        """INSERT INTO listeners
               (app_key, instance_index, handler_method, topic,
                debounce, throttle, once, priority,
                source_location, source_tier)
           VALUES (?, ?, ?, ?, NULL, NULL, 0, 0, 'test.py:1', ?)""",
        (app_key, instance_index, handler_method, topic, source_tier),
    )
    await db_svc.db.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


# ---------------------------------------------------------------------------
# Tests: get_all_jobs_summary
# ---------------------------------------------------------------------------


class TestGetAllJobsSummary:
    async def test_returns_jobs_from_multiple_apps(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """get_all_jobs_summary() aggregates jobs from multiple apps without app_key filter."""
        db_svc, session_id = db

        j1 = await _insert_job(db_svc, app_key="app_alpha", job_name="alpha_job")
        j2 = await _insert_job(db_svc, app_key="app_beta", job_name="beta_job")

        await _insert_execution(db_svc, j1, session_id, status="success", duration_ms=10.0)
        await _insert_execution(db_svc, j2, session_id, status="error", duration_ms=50.0, error_type="ValueError")

        results = await svc.get_all_jobs_summary()

        assert len(results) == 2
        app_keys = {r.app_key for r in results}
        assert app_keys == {"app_alpha", "app_beta"}
        assert all(isinstance(r, JobSummary) for r in results)

    async def test_no_app_key_filter_returns_all(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """All jobs are returned regardless of app_key when no filter is applied."""
        db_svc, _ = db

        for i in range(5):
            await _insert_job(db_svc, app_key=f"app_{i}", job_name=f"job_{i}")

        results = await svc.get_all_jobs_summary()
        assert len(results) == 5

    async def test_includes_error_fields(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Jobs with failed executions have last_error_type, last_error_message populated."""
        db_svc, session_id = db

        j1 = await _insert_job(db_svc, app_key="my_app", job_name="failing_job")
        await _insert_execution(
            db_svc,
            j1,
            session_id,
            status="error",
            duration_ms=5.0,
            error_type="RuntimeError",
            error_message="something went wrong",
        )

        results = await svc.get_all_jobs_summary()
        assert len(results) == 1
        row = results[0]
        assert row.last_error_type == "RuntimeError"
        assert row.last_error_message == "something went wrong"

    async def test_includes_min_max_duration(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """min_duration_ms and max_duration_ms are populated from executions."""
        db_svc, session_id = db

        j1 = await _insert_job(db_svc, app_key="my_app", job_name="timed_job")
        await _insert_execution(db_svc, j1, session_id, status="success", duration_ms=5.0)
        await _insert_execution(db_svc, j1, session_id, status="success", duration_ms=100.0)
        await _insert_execution(db_svc, j1, session_id, status="success", duration_ms=50.0)

        results = await svc.get_all_jobs_summary()
        assert len(results) == 1
        row = results[0]
        assert row.min_duration_ms == pytest.approx(5.0)
        assert row.max_duration_ms == pytest.approx(100.0)

    async def test_no_executions_has_none_min_max(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Jobs with no executions have min/max duration as None (never executed)."""
        db_svc, _ = db

        await _insert_job(db_svc, app_key="my_app", job_name="idle_job")

        results = await svc.get_all_jobs_summary()
        assert len(results) == 1
        row = results[0]
        assert row.min_duration_ms is None
        assert row.max_duration_ms is None

    async def test_since_filter_restricts_by_timestamp(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """since parameter filters executions by timestamp."""
        db_svc, session_id = db

        base_ts = 1_000_000.0
        since_ts = base_ts + 5.0

        j1 = await _insert_job(db_svc, app_key="my_app", job_name="my_job")
        # Before since: counts should not include this
        await _insert_execution(db_svc, j1, session_id, status="success", execution_start_ts=base_ts + 1.0)
        # After since: should count
        await _insert_execution(db_svc, j1, session_id, status="success", execution_start_ts=base_ts + 10.0)

        results = await svc.get_all_jobs_summary(since=since_ts)
        assert len(results) == 1
        row = results[0]
        assert row.total_executions == 1

    async def test_source_tier_app_excludes_framework(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """source_tier='app' excludes framework-tier jobs."""
        db_svc, _ = db

        await _insert_job(db_svc, app_key="my_app", job_name="app_job", source_tier="app")
        await _insert_job(db_svc, app_key="fw_app", job_name="fw_job", source_tier="framework")

        results = await svc.get_all_jobs_summary(source_tier="app")
        assert len(results) == 1
        assert results[0].source_tier == "app"

    async def test_source_tier_all_includes_both_tiers(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """source_tier='all' returns both app and framework tier jobs."""
        db_svc, _ = db

        await _insert_job(db_svc, app_key="my_app", job_name="app_job", source_tier="app")
        await _insert_job(db_svc, app_key="fw_app", job_name="fw_job", source_tier="framework")

        results = await svc.get_all_jobs_summary(source_tier="all")
        assert len(results) == 2


# ---------------------------------------------------------------------------
# Tests: GET /api/scheduler/jobs (global jobs endpoint)
# ---------------------------------------------------------------------------


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
        yield ac, mock_hassette_scheduler


def _make_job_summary(
    job_id: int = 1,
    app_key: str = "my_app",
    job_name: str = "test_job",
) -> JobSummary:
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
        total_executions=3,
        successful=3,
        failed=0,
        last_executed_at=1700000000.0,
        total_duration_ms=90.0,
        avg_duration_ms=30.0,
    )


class TestGlobalJobsEndpointExists:
    async def test_endpoint_returns_200(self, scheduler_client) -> None:
        """GET /api/scheduler/jobs returns 200 and a list."""
        client, mock_hassette = scheduler_client
        mock_hassette.telemetry_query_service.get_all_jobs_summary = AsyncMock(return_value=[])
        mock_hassette.scheduler_service.get_all_jobs = AsyncMock(return_value=[])

        response = await client.get("/api/scheduler/jobs")
        assert response.status_code == 200
        assert response.json() == []


class TestGlobalJobsEndpointMultipleApps:
    async def test_returns_jobs_from_multiple_apps(self, scheduler_client) -> None:
        """GET /api/scheduler/jobs returns jobs from multiple apps."""
        client, mock_hassette = scheduler_client

        db_jobs = [
            _make_job_summary(job_id=1, app_key="app_alpha"),
            _make_job_summary(job_id=2, app_key="app_beta"),
        ]
        mock_hassette.telemetry_query_service.get_all_jobs_summary = AsyncMock(return_value=db_jobs)
        mock_hassette.scheduler_service.get_all_jobs = AsyncMock(return_value=[])

        response = await client.get("/api/scheduler/jobs")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        app_keys = {row["app_key"] for row in data}
        assert app_keys == {"app_alpha", "app_beta"}


class TestGlobalJobsEndpointEnrichesWithLiveData:
    async def test_enriches_with_live_heap_data(self, scheduler_client) -> None:
        """Global jobs endpoint enriches DB rows with live next_run, fire_at, jitter."""
        client, mock_hassette = scheduler_client

        db_summary = _make_job_summary(job_id=42, app_key="my_app")
        mock_hassette.telemetry_query_service.get_all_jobs_summary = AsyncMock(return_value=[db_summary])

        trigger = Every(hours=1)
        live_job = make_real_job(name="test_job", trigger=trigger, jitter=10.0)
        live_job.mark_registered(42)
        live_job.fire_at = live_job.next_run.add(seconds=5.0)
        mock_hassette.scheduler_service.get_all_jobs = AsyncMock(return_value=[live_job])

        response = await client.get("/api/scheduler/jobs")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        row = data[0]

        assert row["next_run"] is not None
        assert isinstance(row["next_run"], float)
        assert row["jitter"] == 10.0
        assert row["fire_at"] is not None


class TestGlobalJobsEndpointDegradedOnHeapFailure:
    async def test_returns_db_rows_when_heap_unavailable(self, scheduler_client) -> None:
        """Returns DB-only rows (no 500) when get_all_jobs() raises."""
        client, mock_hassette = scheduler_client

        db_summary = _make_job_summary(job_id=55)
        mock_hassette.telemetry_query_service.get_all_jobs_summary = AsyncMock(return_value=[db_summary])
        mock_hassette.scheduler_service.get_all_jobs = AsyncMock(side_effect=RuntimeError("heap unavailable"))

        response = await client.get("/api/scheduler/jobs")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["next_run"] is None
        assert data[0]["fire_at"] is None

    async def test_db_error_returns_503(self, scheduler_client) -> None:
        """DB failure returns 503 response."""
        import sqlite3

        client, mock_hassette = scheduler_client

        mock_hassette.telemetry_query_service.get_all_jobs_summary = AsyncMock(
            side_effect=sqlite3.OperationalError("disk I/O error")
        )

        response = await client.get("/api/scheduler/jobs")
        assert response.status_code == 503
        assert response.json() == []


# ---------------------------------------------------------------------------
# Tests: gather_all_listeners returns all tiers
# ---------------------------------------------------------------------------


class TestGatherAllListenersTiers:
    async def test_gather_all_listeners_returns_both_tiers(self) -> None:
        """gather_all_listeners() includes app and framework tier listeners."""
        # Create a manifest snapshot with two instances from different tiers
        runtime = MagicMock()
        telemetry = MagicMock()

        app_listener = ListenerSummary(
            listener_id=1,
            app_key="my_app",
            instance_index=0,
            handler_method="on_event",
            topic="hass.event.state_changed",
            debounce=None,
            throttle=None,
            once=0,
            priority=0,
            predicate_description=None,
            human_description=None,
            source_location="my_app.py:1",
            registration_source=None,
            source_tier="app",
            total_invocations=5,
            successful=5,
            failed=0,
            di_failures=0,
            cancelled=0,
            total_duration_ms=50.0,
            avg_duration_ms=10.0,
            last_invoked_at=None,
            last_error_type=None,
            last_error_message=None,
        )
        fw_listener = ListenerSummary(
            listener_id=2,
            app_key="__hassette__WebSocketService",
            instance_index=0,
            handler_method="on_ws_event",
            topic="internal",
            debounce=None,
            throttle=None,
            once=0,
            priority=0,
            predicate_description=None,
            human_description=None,
            source_location="ws.py:10",
            registration_source=None,
            source_tier="framework",
            total_invocations=10,
            successful=10,
            failed=0,
            di_failures=0,
            cancelled=0,
            total_duration_ms=100.0,
            avg_duration_ms=10.0,
            last_invoked_at=None,
            last_error_type=None,
            last_error_message=None,
        )

        # Mock manifest snapshot with two app instances
        # Simulate gathering listeners from two manifests; each returns a listener
        # The key: get_listener_summary is called WITHOUT source_tier="app" filter
        call_log: list[dict] = []

        async def mock_get_listener_summary(**kwargs: object) -> list[ListenerSummary]:
            call_log.append(dict(kwargs))
            app_key = kwargs.get("app_key", "")
            if app_key == "my_app":
                return [app_listener]
            return [fw_listener]

        telemetry.get_listener_summary = mock_get_listener_summary

        # Build snapshot with two entries
        m1 = MagicMock()
        m1.app_key = "my_app"
        m1.instances = [MagicMock()]
        m1.instances[0].index = 0

        m2 = MagicMock()
        m2.app_key = "__hassette__WebSocketService"
        m2.instances = [MagicMock()]
        m2.instances[0].index = 0

        snapshot = MagicMock()
        snapshot.manifests = [m1, m2]
        runtime.get_all_manifests_snapshot.return_value = snapshot

        result = await gather_all_listeners(runtime, telemetry)

        # Both tiers must be present
        tiers = {ls.source_tier for ls in result}
        assert "app" in tiers
        assert "framework" in tiers

        for call in call_log:
            source_tier_passed = call.get("source_tier")
            assert source_tier_passed == "all", (
                f"gather_all_listeners() must pass source_tier='all'. Got: {source_tier_passed!r}"
            )


# ---------------------------------------------------------------------------
# Tests: ServiceInfoResponse extensions
# ---------------------------------------------------------------------------


class TestServiceInfoResponseExtension:
    def test_service_info_response_has_role_ready_phase_retry_at(self) -> None:
        """ServiceInfoResponse has role, ready_phase, retry_at fields."""
        from hassette.web.models import ServiceInfoResponse

        svc = ServiceInfoResponse(
            name="WebSocketService",
            status="running",
            role="Service",
            ready_phase="connected",
            retry_at=1700000000.0,
        )
        assert svc.role == "Service"
        assert svc.ready_phase == "connected"
        assert svc.retry_at == 1700000000.0

    def test_service_info_response_defaults(self) -> None:
        """ServiceInfoResponse has sensible defaults when role/ready_phase/retry_at omitted."""
        from hassette.web.models import ServiceInfoResponse

        svc = ServiceInfoResponse(name="SomeService", status="running")
        assert svc.role == ""
        assert svc.ready_phase is None
        assert svc.retry_at is None

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
    async def test_health_endpoint_returns_services_with_role(self, scheduler_client) -> None:
        """GET /api/health returns services array with role field populated."""
        client, mock_hassette = scheduler_client

        mock_child = MagicMock()
        mock_child.class_name = "WebSocketService"
        mock_child.status = ResourceStatus.RUNNING
        mock_child.role = ResourceRole.SERVICE
        mock_child._ready_reason = "connected"
        mock_child._retry_at = None

        mock_hassette.children = [mock_child]

        # Wire runtime_query_service so it uses a real get_system_status
        rqs = create_mock_runtime_query_service(mock_hassette)
        mock_hassette.runtime_query_service = rqs

        response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "services" in data
        # Each service entry should have a role field
        for svc in data["services"]:
            assert "role" in svc
