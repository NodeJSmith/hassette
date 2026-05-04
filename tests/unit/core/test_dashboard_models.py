"""Tests for WP16 backend additions: version, run_rate, source_location, recent_invocations_1h,
boot_issues, activity feed, and sparkline buckets.
"""

from hassette.core.domain_models import BootIssue, SystemStatus
from hassette.web.models import (
    ActivityBucket,
    AppManifestResponse,
    DashboardKpisResponse,
    HandlerErrorEntry,
    JobErrorEntry,
)

# ---------------------------------------------------------------------------
# Subtask 1: version field in SystemStatus and response models
# ---------------------------------------------------------------------------


class TestVersionField:
    def test_system_status_has_version(self) -> None:
        """SystemStatus domain model includes a version field."""
        status = SystemStatus(
            status="ok",
            websocket_connected=True,
            uptime_seconds=42.0,
            entity_count=10,
            app_count=2,
            services_running=[],
            version="1.2.3",
            boot_issues=[],
        )
        assert status.version == "1.2.3"

    def test_system_status_default_version(self) -> None:
        """SystemStatus version has a default (computed from package metadata)."""
        status = SystemStatus(
            status="ok",
            websocket_connected=True,
            uptime_seconds=0.0,
            entity_count=0,
            app_count=0,
            services_running=[],
        )
        # Must be a non-empty string
        assert isinstance(status.version, str)
        assert len(status.version) > 0


# ---------------------------------------------------------------------------
# Subtask 2: runs_per_hour in DashboardKpisResponse
# ---------------------------------------------------------------------------


class TestRunsPerHour:
    def test_runs_per_hour_present_in_model(self) -> None:
        """DashboardKpisResponse accepts runs_per_hour field."""
        kpis = DashboardKpisResponse(
            total_handlers=10,
            total_jobs=5,
            total_invocations=100,
            total_executions=50,
            total_errors=2,
            total_timed_out=0,
            total_job_errors=1,
            total_job_timed_out=0,
            avg_handler_duration_ms=10.0,
            avg_job_duration_ms=20.0,
            error_rate=1.0,
            error_rate_class="low",
            runs_per_hour=150.0,
        )
        assert kpis.runs_per_hour == 150.0

    def test_runs_per_hour_nullable(self) -> None:
        """runs_per_hour can be None for very short windows."""
        kpis = DashboardKpisResponse(
            total_handlers=0,
            total_jobs=0,
            total_invocations=5,
            total_executions=0,
            total_errors=0,
            total_timed_out=0,
            total_job_errors=0,
            total_job_timed_out=0,
            avg_handler_duration_ms=0.0,
            avg_job_duration_ms=0.0,
            error_rate=0.0,
            error_rate_class="low",
            runs_per_hour=None,
        )
        assert kpis.runs_per_hour is None

    def test_runs_per_hour_defaults_none(self) -> None:
        """runs_per_hour defaults to None when omitted."""
        kpis = DashboardKpisResponse(
            total_handlers=0,
            total_jobs=0,
            total_invocations=0,
            total_executions=0,
            total_errors=0,
            total_timed_out=0,
            total_job_errors=0,
            total_job_timed_out=0,
            avg_handler_duration_ms=0.0,
            avg_job_duration_ms=0.0,
            error_rate=0.0,
            error_rate_class="low",
        )
        assert kpis.runs_per_hour is None


# ---------------------------------------------------------------------------
# Subtask 3: source_location in error entries
# ---------------------------------------------------------------------------


class TestSourceLocationOnErrorEntries:
    def test_handler_error_entry_has_source_location(self) -> None:
        """HandlerErrorEntry includes source_location field."""
        entry = HandlerErrorEntry(
            listener_id=1,
            topic="hass.state_changed",
            handler_method="on_event",
            error_message="boom",
            error_type="ValueError",
            execution_start_ts=1700000000.0,
            app_key="my_app",
            source_location="my_app.py:42",
        )
        assert entry.source_location == "my_app.py:42"

    def test_handler_error_entry_source_location_nullable(self) -> None:
        """HandlerErrorEntry source_location defaults to None."""
        entry = HandlerErrorEntry(
            listener_id=1,
            topic="hass.state_changed",
            handler_method="on_event",
            error_message="boom",
            error_type="ValueError",
            execution_start_ts=1700000000.0,
            app_key="my_app",
        )
        assert entry.source_location is None

    def test_job_error_entry_has_source_location(self) -> None:
        """JobErrorEntry includes source_location field."""
        entry = JobErrorEntry(
            job_id=2,
            job_name="my_job",
            error_message="oops",
            error_type="RuntimeError",
            execution_start_ts=1700000000.0,
            app_key="my_app",
            source_location="scheduler.py:99",
        )
        assert entry.source_location == "scheduler.py:99"

    def test_job_error_entry_source_location_nullable(self) -> None:
        """JobErrorEntry source_location defaults to None."""
        entry = JobErrorEntry(
            job_id=2,
            job_name="my_job",
            error_message="oops",
            error_type="RuntimeError",
            execution_start_ts=1700000000.0,
            app_key="my_app",
        )
        assert entry.source_location is None


# ---------------------------------------------------------------------------
# Subtask 4: recent_invocations_1h in AppManifestResponse
# ---------------------------------------------------------------------------


class TestRecentInvocations1h:
    def test_app_manifest_response_has_recent_invocations(self) -> None:
        """AppManifestResponse accepts recent_invocations_1h field."""
        manifest = AppManifestResponse(
            app_key="my_app",
            class_name="MyApp",
            display_name="My App",
            filename="my_app.py",
            enabled=True,
            auto_loaded=True,
            status="running",
            instance_count=1,
            recent_invocations_1h=42,
        )
        assert manifest.recent_invocations_1h == 42

    def test_app_manifest_response_recent_invocations_default_zero(self) -> None:
        """AppManifestResponse recent_invocations_1h defaults to 0."""
        manifest = AppManifestResponse(
            app_key="my_app",
            class_name="MyApp",
            display_name="My App",
            filename="my_app.py",
            enabled=True,
            auto_loaded=True,
            status="running",
            instance_count=1,
        )
        assert manifest.recent_invocations_1h == 0


# ---------------------------------------------------------------------------
# Subtask 5: boot_issues in SystemStatus
# ---------------------------------------------------------------------------


class TestBootIssues:
    def test_system_status_has_boot_issues(self) -> None:
        """SystemStatus includes boot_issues list."""
        issues = [
            BootIssue(severity="err", label="Config invalid", detail="Missing token"),
            BootIssue(severity="warn", label="App blocked", detail="my_app: import failed"),
        ]
        status = SystemStatus(
            status="ok",
            websocket_connected=True,
            uptime_seconds=1.0,
            entity_count=0,
            app_count=0,
            services_running=[],
            boot_issues=issues,
        )
        assert len(status.boot_issues) == 2
        assert status.boot_issues[0].severity == "err"
        assert status.boot_issues[0].label == "Config invalid"
        assert status.boot_issues[1].severity == "warn"

    def test_boot_issues_defaults_empty(self) -> None:
        """boot_issues defaults to an empty list."""
        status = SystemStatus(
            status="ok",
            websocket_connected=True,
            uptime_seconds=0.0,
            entity_count=0,
            app_count=0,
            services_running=[],
        )
        assert status.boot_issues == []

    def test_boot_issue_model(self) -> None:
        """BootIssue accepts severity, label, detail."""
        issue = BootIssue(severity="warn", label="Degraded", detail="Some detail")
        assert issue.severity == "warn"
        assert issue.label == "Degraded"
        assert issue.detail == "Some detail"


# ---------------------------------------------------------------------------
# Subtask 7: activity_buckets in DashboardKpisResponse
# ---------------------------------------------------------------------------


class TestActivityBuckets:
    def test_kpis_has_activity_buckets(self) -> None:
        """DashboardKpisResponse accepts activity_buckets list."""
        buckets = [ActivityBucket(ok=10, err=2) for _ in range(12)]
        kpis = DashboardKpisResponse(
            total_handlers=0,
            total_jobs=0,
            total_invocations=0,
            total_executions=0,
            total_errors=0,
            total_timed_out=0,
            total_job_errors=0,
            total_job_timed_out=0,
            avg_handler_duration_ms=0.0,
            avg_job_duration_ms=0.0,
            error_rate=0.0,
            error_rate_class="low",
            activity_buckets=buckets,
        )
        assert len(kpis.activity_buckets) == 12
        assert kpis.activity_buckets[0].ok == 10
        assert kpis.activity_buckets[0].err == 2

    def test_activity_buckets_defaults_empty(self) -> None:
        """activity_buckets defaults to an empty list."""
        kpis = DashboardKpisResponse(
            total_handlers=0,
            total_jobs=0,
            total_invocations=0,
            total_executions=0,
            total_errors=0,
            total_timed_out=0,
            total_job_errors=0,
            total_job_timed_out=0,
            avg_handler_duration_ms=0.0,
            avg_job_duration_ms=0.0,
            error_rate=0.0,
            error_rate_class="low",
        )
        assert kpis.activity_buckets == []

    def test_activity_bucket_model(self) -> None:
        """ActivityBucket has ok and err integer fields."""
        bucket = ActivityBucket(ok=5, err=1)
        assert bucket.ok == 5
        assert bucket.err == 1
