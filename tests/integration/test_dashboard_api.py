"""Integration tests for WP16 API additions:
- GET /api/health returns version and boot_issues
- GET /api/telemetry/dashboard/kpis returns runs_per_hour and activity_buckets
- GET /api/dashboard/activity returns merged activity feed
- AppManifestResponse includes recent_invocations_1h
- Error entries include source_location
"""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from hassette.core.domain_models import BootIssue, SystemStatus
from hassette.core.telemetry_models import (
    GlobalSummary,
    JobGlobalStats,
    ListenerGlobalStats,
)
from hassette.test_utils.web_mocks import create_hassette_stub, create_mock_runtime_query_service
from hassette.web.app import create_fastapi_app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def stub():
    """Create a Hassette stub for WP16 tests."""
    return create_hassette_stub(run_web_ui=False)


@pytest.fixture
def rqs(stub):
    """Create a RuntimeQueryService wired to the stub."""
    return create_mock_runtime_query_service(stub)


@pytest.fixture
async def client(stub, rqs):  # noqa: ARG001 — rqs wired to stub as side-effect
    app = create_fastapi_app(stub)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, stub


# ---------------------------------------------------------------------------
# Subtask 1: version in /api/health
# ---------------------------------------------------------------------------


class TestVersionInHealth:
    async def test_health_returns_version(self, client) -> None:
        """GET /api/health response includes a 'version' field."""
        ac, stub = client
        # Wire get_system_status to return a status with version
        stub.runtime_query_service.get_system_status = MagicMock(
            return_value=SystemStatus(
                status="ok",
                websocket_connected=True,
                uptime_seconds=10.0,
                entity_count=5,
                app_count=1,
                services_running=[],
                version="0.99.0",
                boot_issues=[],
            )
        )
        response = await ac.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "version" in data
        assert data["version"] == "0.99.0"

    async def test_health_returns_boot_issues(self, client) -> None:
        """GET /api/health response includes 'boot_issues' list."""
        ac, stub = client
        stub.runtime_query_service.get_system_status = MagicMock(
            return_value=SystemStatus(
                status="ok",
                websocket_connected=True,
                uptime_seconds=5.0,
                entity_count=0,
                app_count=0,
                services_running=[],
                version="1.0.0",
                boot_issues=[
                    BootIssue(severity="warn", label="App blocked", detail="my_app: import error"),
                ],
            )
        )
        response = await ac.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "boot_issues" in data
        assert len(data["boot_issues"]) == 1
        issue = data["boot_issues"][0]
        assert issue["severity"] == "warn"
        assert issue["label"] == "App blocked"
        assert "import error" in issue["detail"]

    async def test_health_boot_issues_empty_by_default(self, client) -> None:
        """GET /api/health with no boot issues returns an empty list."""
        ac, stub = client
        stub.runtime_query_service.get_system_status = MagicMock(
            return_value=SystemStatus(
                status="ok",
                websocket_connected=True,
                uptime_seconds=1.0,
                entity_count=0,
                app_count=0,
                services_running=[],
            )
        )
        response = await ac.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["boot_issues"] == []


# ---------------------------------------------------------------------------
# Subtask 2: runs_per_hour in /api/telemetry/dashboard/kpis
# ---------------------------------------------------------------------------


class TestRunsPerHourInKpis:
    async def test_kpis_runs_per_hour_computed(self, client) -> None:
        """Dashboard KPIs endpoint returns computed runs_per_hour."""
        ac, stub = client
        now = time.time()
        one_hour_ago = now - 3600.0

        stub.telemetry_query_service.get_global_summary = AsyncMock(
            return_value=GlobalSummary(
                listeners=ListenerGlobalStats(
                    total_listeners=5,
                    invoked_listeners=5,
                    total_invocations=120,
                    total_errors=0,
                    total_di_failures=0,
                    avg_duration_ms=None,
                ),
                jobs=JobGlobalStats(
                    total_jobs=2,
                    executed_jobs=2,
                    total_executions=60,
                    total_errors=0,
                ),
            )
        )

        response = await ac.get(f"/api/telemetry/dashboard/kpis?since={one_hour_ago}")
        assert response.status_code == 200
        data = response.json()
        assert "runs_per_hour" in data
        # 120 + 60 = 180 in ~1 hour window → ~180 runs/hr
        assert data["runs_per_hour"] is not None
        assert data["runs_per_hour"] == pytest.approx(180.0, abs=1.0)

    async def test_kpis_runs_per_hour_null_for_short_window(self, client) -> None:
        """runs_per_hour is null when window < 1 minute."""
        ac, stub = client
        now = time.time()
        thirty_sec_ago = now - 30.0  # 30 seconds — less than 1 minute

        stub.telemetry_query_service.get_global_summary = AsyncMock(
            return_value=GlobalSummary(
                listeners=ListenerGlobalStats(
                    total_listeners=1,
                    invoked_listeners=1,
                    total_invocations=5,
                    total_errors=0,
                    total_di_failures=0,
                    avg_duration_ms=None,
                ),
                jobs=JobGlobalStats(
                    total_jobs=0,
                    executed_jobs=0,
                    total_executions=0,
                    total_errors=0,
                ),
            )
        )

        response = await ac.get(f"/api/telemetry/dashboard/kpis?since={thirty_sec_ago}")
        assert response.status_code == 200
        data = response.json()
        assert data["runs_per_hour"] is None

    async def test_kpis_runs_per_hour_null_when_no_since(self, client) -> None:
        """runs_per_hour is null when no since parameter is provided."""
        ac, stub = client

        stub.telemetry_query_service.get_global_summary = AsyncMock(
            return_value=GlobalSummary(
                listeners=ListenerGlobalStats(
                    total_listeners=0,
                    invoked_listeners=0,
                    total_invocations=10,
                    total_errors=0,
                    total_di_failures=0,
                    avg_duration_ms=None,
                ),
                jobs=JobGlobalStats(
                    total_jobs=0,
                    executed_jobs=0,
                    total_executions=0,
                    total_errors=0,
                ),
            )
        )

        response = await ac.get("/api/telemetry/dashboard/kpis")
        assert response.status_code == 200
        data = response.json()
        assert data["runs_per_hour"] is None


# ---------------------------------------------------------------------------
# Subtask 3: source_location in dashboard/errors
# ---------------------------------------------------------------------------


class TestSourceLocationInErrors:
    async def test_dashboard_errors_handler_has_source_location(self, client) -> None:
        """Dashboard error entries include source_location field."""
        ac, stub = client
        from hassette.core.telemetry_models import HandlerErrorRecord

        stub.telemetry_query_service.get_recent_errors = AsyncMock(
            return_value=[
                HandlerErrorRecord(
                    listener_id=1,
                    app_key="my_app",
                    handler_method="on_event",
                    topic="hass.state_changed",
                    execution_start_ts=time.time() - 10.0,
                    duration_ms=5.0,
                    source_tier="app",
                    error_type="ValueError",
                    error_message="bad value",
                    error_traceback=None,
                    source_location="my_app.py:42",
                )
            ]
        )

        response = await ac.get("/api/telemetry/dashboard/errors")
        assert response.status_code == 200
        data = response.json()
        errors = data["errors"]
        assert len(errors) == 1
        assert errors[0]["source_location"] == "my_app.py:42"

    async def test_dashboard_errors_job_has_source_location(self, client) -> None:
        """Dashboard job error entries include source_location field."""
        ac, stub = client
        from hassette.core.telemetry_models import JobErrorRecord

        stub.telemetry_query_service.get_recent_errors = AsyncMock(
            return_value=[
                JobErrorRecord(
                    job_id=7,
                    app_key="my_app",
                    job_name="nightly_job",
                    handler_method="run",
                    execution_start_ts=time.time() - 5.0,
                    duration_ms=10.0,
                    source_tier="app",
                    error_type="RuntimeError",
                    error_message="failed",
                    error_traceback=None,
                    source_location="scheduler.py:99",
                )
            ]
        )

        response = await ac.get("/api/telemetry/dashboard/errors")
        assert response.status_code == 200
        data = response.json()
        errors = data["errors"]
        assert len(errors) == 1
        assert errors[0]["source_location"] == "scheduler.py:99"

    async def test_dashboard_errors_source_location_null_when_missing(self, client) -> None:
        """source_location is null when listener/job has no source_location."""
        ac, stub = client
        from hassette.core.telemetry_models import HandlerErrorRecord

        stub.telemetry_query_service.get_recent_errors = AsyncMock(
            return_value=[
                HandlerErrorRecord(
                    listener_id=None,
                    app_key=None,
                    handler_method=None,
                    topic=None,
                    execution_start_ts=time.time() - 10.0,
                    duration_ms=5.0,
                    source_tier="app",
                    error_type="ValueError",
                    error_message="bad",
                    error_traceback=None,
                    source_location=None,
                )
            ]
        )

        response = await ac.get("/api/telemetry/dashboard/errors")
        assert response.status_code == 200
        data = response.json()
        errors = data["errors"]
        assert len(errors) == 1
        assert errors[0]["source_location"] is None


# ---------------------------------------------------------------------------
# Subtask 6: GET /api/dashboard/activity
# ---------------------------------------------------------------------------


class TestDashboardActivityEndpoint:
    async def test_activity_endpoint_exists(self, client) -> None:
        """GET /api/dashboard/activity returns 200."""
        ac, stub = client
        stub.telemetry_query_service.get_activity_feed = AsyncMock(return_value=[])

        response = await ac.get("/api/telemetry/dashboard/activity")
        assert response.status_code == 200

    async def test_activity_returns_list(self, client) -> None:
        """GET /api/dashboard/activity returns a list of activity entries."""
        ac, stub = client
        stub.telemetry_query_service.get_activity_feed = AsyncMock(return_value=[])

        response = await ac.get("/api/telemetry/dashboard/activity")
        assert response.status_code == 200
        assert response.json() == []

    async def test_activity_returns_entries(self, client) -> None:
        """GET /api/dashboard/activity returns populated entries."""
        ac, stub = client
        from hassette.core.telemetry_models import ActivityFeedEntry

        entries = [
            ActivityFeedEntry(
                status="success",
                timestamp=1700000010.0,
                app_key="my_app",
                handler_name="on_event",
                duration_ms=5.0,
                error_type=None,
                kind="handler",
            ),
            ActivityFeedEntry(
                status="error",
                timestamp=1700000005.0,
                app_key="other_app",
                handler_name="run_job",
                duration_ms=20.0,
                error_type="ValueError",
                kind="job",
            ),
        ]
        stub.telemetry_query_service.get_activity_feed = AsyncMock(return_value=entries)

        response = await ac.get("/api/telemetry/dashboard/activity")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        # Must be sorted desc by timestamp
        assert data[0]["timestamp"] == pytest.approx(1700000010.0)
        assert data[0]["kind"] == "handler"
        assert data[1]["timestamp"] == pytest.approx(1700000005.0)
        assert data[1]["kind"] == "job"
        assert data[1]["error_type"] == "ValueError"

    async def test_activity_accepts_limit_param(self, client) -> None:
        """GET /api/dashboard/activity accepts a limit query param."""
        ac, stub = client
        stub.telemetry_query_service.get_activity_feed = AsyncMock(return_value=[])

        response = await ac.get("/api/telemetry/dashboard/activity?limit=10")
        assert response.status_code == 200
        stub.telemetry_query_service.get_activity_feed.assert_awaited_once()
        call_kwargs = stub.telemetry_query_service.get_activity_feed.call_args
        assert call_kwargs.kwargs.get("limit") == 10 or (call_kwargs.args and call_kwargs.args[0] == 10)

    async def test_activity_accepts_since_param(self, client) -> None:
        """GET /api/dashboard/activity accepts a since query param."""
        ac, stub = client
        stub.telemetry_query_service.get_activity_feed = AsyncMock(return_value=[])
        since_ts = time.time() - 3600.0

        response = await ac.get(f"/api/telemetry/dashboard/activity?since={since_ts}")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Subtask 7: activity_buckets in /api/telemetry/dashboard/kpis
# ---------------------------------------------------------------------------


class TestActivityBucketsInKpis:
    async def test_kpis_has_activity_buckets(self, client) -> None:
        """Dashboard KPIs endpoint returns activity_buckets with 12 items."""
        ac, stub = client
        now = time.time()
        one_hour_ago = now - 3600.0

        stub.telemetry_query_service.get_global_summary = AsyncMock(
            return_value=GlobalSummary(
                listeners=ListenerGlobalStats(
                    total_listeners=1,
                    invoked_listeners=1,
                    total_invocations=12,
                    total_errors=0,
                    total_di_failures=0,
                    avg_duration_ms=None,
                ),
                jobs=JobGlobalStats(
                    total_jobs=0,
                    executed_jobs=0,
                    total_executions=0,
                    total_errors=0,
                ),
            )
        )
        stub.telemetry_query_service.get_activity_buckets = AsyncMock(return_value=[(1, 0)] * 12)

        response = await ac.get(f"/api/telemetry/dashboard/kpis?since={one_hour_ago}")
        assert response.status_code == 200
        data = response.json()
        assert "activity_buckets" in data
        assert len(data["activity_buckets"]) == 12
        for bucket in data["activity_buckets"]:
            assert "ok" in bucket
            assert "err" in bucket

    async def test_kpis_activity_buckets_empty_when_no_since(self, client) -> None:
        """activity_buckets is empty when no since parameter is given."""
        ac, stub = client
        stub.telemetry_query_service.get_global_summary = AsyncMock(
            return_value=GlobalSummary(
                listeners=ListenerGlobalStats(
                    total_listeners=0,
                    invoked_listeners=0,
                    total_invocations=0,
                    total_errors=0,
                    total_di_failures=0,
                    avg_duration_ms=None,
                ),
                jobs=JobGlobalStats(
                    total_jobs=0,
                    executed_jobs=0,
                    total_executions=0,
                    total_errors=0,
                ),
            )
        )

        response = await ac.get("/api/telemetry/dashboard/kpis")
        assert response.status_code == 200
        data = response.json()
        assert data["activity_buckets"] == []
