"""Factory functions for e2e test mock data.

These build the seed data used by the ``mock_hassette`` session fixture in
``conftest.py``.  Keeping construction here reduces conftest.py to the
fixture scaffolding only and makes individual seed builders reusable.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from hassette.core.app_registry import AppInstanceInfo, AppManifestInfo, AppStatusSnapshot
from hassette.core.telemetry_models import (
    AppHealthSummary,
    GlobalSummary,
    HandlerErrorRecord,
    HandlerInvocation,
    JobErrorRecord,
    JobExecution,
    JobGlobalStats,
    JobSummary,
    ListenerGlobalStats,
    ListenerSummary,
    SessionRecord,
)
from hassette.test_utils.web_helpers import make_job, make_manifest
from hassette.types.enums import ResourceStatus

# ──────────────────────────────────────────────────────────────────────
# Manifest builders
# ──────────────────────────────────────────────────────────────────────


def build_manifests() -> list[AppManifestInfo]:
    """Build a rich set of app manifests for e2e tests."""
    return [
        make_manifest(
            app_key="my_app",
            class_name="MyApp",
            display_name="My App",
            filename="my_app.py",
            status="running",
            instance_count=1,
            instances=[
                AppInstanceInfo(
                    app_key="my_app",
                    index=0,
                    instance_name="MyApp[0]",
                    class_name="MyApp",
                    status=ResourceStatus.RUNNING,
                    owner_id="MyApp.MyApp[0]",
                )
            ],
        ),
        make_manifest(
            app_key="other_app",
            class_name="OtherApp",
            display_name="Other App",
            filename="other_app.py",
            status="stopped",
            instance_count=0,
        ),
        make_manifest(
            app_key="broken_app",
            class_name="BrokenApp",
            display_name="Broken App",
            filename="broken_app.py",
            status="failed",
            instance_count=1,
            instances=[
                AppInstanceInfo(
                    app_key="broken_app",
                    index=0,
                    instance_name="BrokenApp[0]",
                    class_name="BrokenApp",
                    status=ResourceStatus.FAILED,
                    error_message="Init error: bad config",
                    error_traceback=(
                        'Traceback (most recent call last):\n  File "broken_app.py", line 10, in '
                        'on_initialize\n    raise ValueError("bad config")\nValueError: bad config\n'
                    ),
                )
            ],
            error_message="Init error: bad config",
            error_traceback=(
                'Traceback (most recent call last):\n  File "broken_app.py", line 10, in on_initialize\n'
                '    raise ValueError("bad config")\nValueError: bad config\n'
            ),
        ),
        make_manifest(
            app_key="disabled_app",
            class_name="DisabledApp",
            display_name="Disabled App",
            filename="disabled_app.py",
            enabled=False,
            status="disabled",
            instance_count=0,
        ),
        make_manifest(
            app_key="nosource_app",
            class_name="NoSourceApp",
            display_name="No Source App",
            filename="nosource_app.py",
            status="running",
            instance_count=1,
            instances=[
                AppInstanceInfo(
                    app_key="nosource_app",
                    index=0,
                    instance_name="NoSourceApp[0]",
                    class_name="NoSourceApp",
                    status=ResourceStatus.RUNNING,
                    owner_id="NoSourceApp.NoSourceApp[0]",
                ),
            ],
        ),
        make_manifest(
            app_key="multi_app",
            class_name="MultiApp",
            display_name="Multi App",
            filename="multi_app.py",
            status="running",
            instance_count=3,
            instances=[
                AppInstanceInfo(
                    app_key="multi_app",
                    index=0,
                    instance_name="MultiApp[0]",
                    class_name="MultiApp",
                    status=ResourceStatus.RUNNING,
                    owner_id="MultiApp.MultiApp[0]",
                ),
                AppInstanceInfo(
                    app_key="multi_app",
                    index=1,
                    instance_name="MultiApp[1]",
                    class_name="MultiApp",
                    status=ResourceStatus.RUNNING,
                    owner_id="MultiApp.MultiApp[1]",
                ),
                AppInstanceInfo(
                    app_key="multi_app",
                    index=2,
                    instance_name="MultiApp[2]",
                    class_name="MultiApp",
                    status=ResourceStatus.RUNNING,
                    owner_id="MultiApp.MultiApp[2]",
                ),
            ],
        ),
    ]


def build_old_snapshot() -> AppStatusSnapshot:
    """Build the legacy AppStatusSnapshot used to seed mock_hassette."""
    return AppStatusSnapshot(
        running=[
            AppInstanceInfo(
                app_key="my_app",
                index=0,
                instance_name="MyApp[0]",
                class_name="MyApp",
                status=ResourceStatus.RUNNING,
                owner_id="MyApp.MyApp[0]",
            ),
            AppInstanceInfo(
                app_key="nosource_app",
                index=0,
                instance_name="NoSourceApp[0]",
                class_name="NoSourceApp",
                status=ResourceStatus.RUNNING,
                owner_id="NoSourceApp.NoSourceApp[0]",
            ),
        ],
        failed=[
            AppInstanceInfo(
                app_key="broken_app",
                index=0,
                instance_name="BrokenApp[0]",
                class_name="BrokenApp",
                status=ResourceStatus.FAILED,
                error_message="Init error: bad config",
            ),
        ],
    )


def build_scheduler_jobs() -> list[SimpleNamespace]:
    """Build scheduler job stubs for e2e seed data."""
    return [
        make_job(trigger_detail="PT30S", app_key="my_app", instance_index=0),
        make_job(
            job_id="job-2",
            name="morning_routine",
            next_run="2024-01-01T07:00:00",
            trigger_type="cron",
            trigger_detail="0 7 * * * 0",
            app_key="my_app",
            instance_index=0,
        ),
    ]


# ──────────────────────────────────────────────────────────────────────
# Telemetry seed data builders
# ──────────────────────────────────────────────────────────────────────


def build_listener_telemetry() -> dict[str, list[ListenerSummary]]:
    """Build per-app listener summaries for e2e tests."""
    telemetry_listeners_my_app = [
        ListenerSummary(
            listener_id=1,
            handler_method="on_light_change",
            topic="state_changed.light.kitchen",
            app_key="my_app",
            instance_index=0,
            debounce=0.5,
            throttle=None,
            once=0,
            priority=0,
            predicate_description="EntityMatches(entity_id='light.kitchen')",
            human_description=None,
            source_location="my_app.py:15",
            registration_source="on_initialize",
            total_invocations=10,
            successful=9,
            failed=1,
            di_failures=0,
            cancelled=0,
            total_duration_ms=20.0,
            avg_duration_ms=2.0,
            min_duration_ms=1.0,
            max_duration_ms=5.0,
            last_invoked_at=1704067200.0,
            last_error_type="ValueError",
            last_error_message="Bad state value",
        ),
        ListenerSummary(
            listener_id=2,
            handler_method="on_temp_update",
            topic="state_changed.sensor.temperature",
            app_key="my_app",
            instance_index=0,
            debounce=None,
            throttle=1.0,
            once=0,
            priority=0,
            predicate_description="EntityMatches(entity_id='sensor.temperature')",
            human_description="React to temperature sensor changes above threshold",
            source_location="my_app.py:22",
            registration_source="on_initialize",
            total_invocations=20,
            successful=20,
            failed=0,
            di_failures=0,
            cancelled=0,
            total_duration_ms=40.0,
            avg_duration_ms=2.0,
            min_duration_ms=1.0,
            max_duration_ms=5.0,
            last_invoked_at=1704067100.0,
            last_error_type=None,
            last_error_message=None,
        ),
    ]
    # broken_app listeners — registered before the app failed during init.
    telemetry_listeners_broken_app = [
        ListenerSummary(
            listener_id=3,
            handler_method="on_door_open",
            topic="state_changed.binary_sensor.door",
            app_key="broken_app",
            instance_index=0,
            debounce=None,
            throttle=None,
            once=0,
            priority=0,
            predicate_description="EntityMatches(entity_id='binary_sensor.door')",
            human_description="Lock door after 5 minutes of being open",
            source_location="broken_app.py:8",
            registration_source="on_initialize",
            total_invocations=3,
            successful=1,
            failed=2,
            di_failures=0,
            cancelled=0,
            total_duration_ms=15.0,
            avg_duration_ms=5.0,
            min_duration_ms=2.0,
            max_duration_ms=10.0,
            last_invoked_at=1704067050.0,
            last_error_type="RuntimeError",
            last_error_message="Lock service timed out",
        ),
    ]
    # nosource_app listeners — empty source fields for testing hidden source display.
    telemetry_listeners_nosource_app = [
        ListenerSummary(
            listener_id=100,
            handler_method="on_event",
            topic="state_changed.switch.fan",
            app_key="nosource_app",
            instance_index=0,
            debounce=None,
            throttle=None,
            once=0,
            priority=0,
            predicate_description=None,
            human_description=None,
            source_location="",
            registration_source=None,
            total_invocations=1,
            successful=1,
            failed=0,
            di_failures=0,
            cancelled=0,
            total_duration_ms=1.0,
            avg_duration_ms=1.0,
            min_duration_ms=1.0,
            max_duration_ms=1.0,
            last_invoked_at=1704067000.0,
            last_error_type=None,
            last_error_message=None,
        ),
    ]
    return {
        "my_app": telemetry_listeners_my_app,
        "broken_app": telemetry_listeners_broken_app,
        "nosource_app": telemetry_listeners_nosource_app,
    }


def build_job_telemetry() -> dict[str, list[JobSummary]]:
    """Build per-app job summaries for e2e tests."""
    telemetry_jobs_my_app = [
        JobSummary(
            job_id=1,
            app_key="my_app",
            instance_index=0,
            job_name="check_lights",
            handler_method="check_lights",
            trigger_type="interval",
            args_json="[]",
            kwargs_json="{}",
            source_location="my_app.py:30",
            registration_source="on_initialize",
            total_executions=15,
            successful=14,
            failed=1,
            last_executed_at=1704067200.0,
            total_duration_ms=52.5,
            avg_duration_ms=3.5,
        ),
        JobSummary(
            job_id=2,
            app_key="my_app",
            instance_index=0,
            job_name="morning_routine",
            handler_method="morning_routine",
            trigger_type="cron",
            args_json="[]",
            kwargs_json="{}",
            source_location="my_app.py:45",
            registration_source="on_initialize",
            total_executions=5,
            successful=5,
            failed=0,
            last_executed_at=1704067100.0,
            total_duration_ms=60.0,
            avg_duration_ms=12.0,
        ),
    ]
    telemetry_jobs_broken_app = [
        JobSummary(
            job_id=3,
            app_key="broken_app",
            instance_index=0,
            job_name="retry_connection",
            handler_method="retry_connection",
            trigger_type="interval",
            args_json="[]",
            kwargs_json="{}",
            source_location="broken_app.py:20",
            registration_source="on_initialize",
            total_executions=8,
            successful=3,
            failed=5,
            last_executed_at=1704067050.0,
            total_duration_ms=64.0,
            avg_duration_ms=8.0,
        ),
    ]
    # nosource_app jobs — empty source fields for testing hidden source display.
    telemetry_jobs_nosource_app = [
        JobSummary(
            job_id=100,
            app_key="nosource_app",
            instance_index=0,
            job_name="poll_sensor",
            handler_method="poll_sensor",
            trigger_type="interval",
            args_json="[]",
            kwargs_json="{}",
            source_location="",
            registration_source=None,
            total_executions=2,
            successful=2,
            failed=0,
            last_executed_at=1704067000.0,
            total_duration_ms=2.0,
            avg_duration_ms=1.0,
        ),
    ]
    return {
        "my_app": telemetry_jobs_my_app,
        "broken_app": telemetry_jobs_broken_app,
        "nosource_app": telemetry_jobs_nosource_app,
    }


def build_handler_invocations() -> list[HandlerInvocation]:
    """Build handler invocation records for e2e drill-down tests."""
    return [
        HandlerInvocation(
            execution_start_ts=1704067200.0,
            duration_ms=2.5,
            status="success",
            error_type=None,
            error_message=None,
            error_traceback=None,
        ),
        HandlerInvocation(
            execution_start_ts=1704067100.0,
            duration_ms=3.1,
            status="error",
            error_type="ValueError",
            error_message="Bad state value",
            error_traceback=(
                'Traceback (most recent call last):\n  File "my_app.py", line 18, in '
                'on_light_change\n    raise ValueError("Bad state value")\nValueError: Bad state value\n'
            ),
        ),
    ]


def build_job_executions() -> list[JobExecution]:
    """Build job execution records for e2e drill-down tests."""
    return [
        JobExecution(
            execution_start_ts=1704067200.0,
            duration_ms=3.0,
            status="success",
            error_type=None,
            error_message=None,
        ),
        JobExecution(
            execution_start_ts=1704067100.0,
            duration_ms=4.2,
            status="error",
            error_type="TimeoutError",
            error_message="Light service unavailable",
        ),
    ]


def build_session_list() -> list[SessionRecord]:
    """Build session records for the sessions page."""
    return [
        SessionRecord(
            id=1,
            started_at=1704067200.0,
            stopped_at=None,
            status="running",
            error_type=None,
            error_message=None,
            duration_seconds=3600.0,
        ),
        SessionRecord(
            id=2,
            started_at=1704060000.0,
            stopped_at=1704063600.0,
            status="success",
            error_type=None,
            error_message=None,
            duration_seconds=3600.0,
        ),
        SessionRecord(
            id=3,
            started_at=1704050000.0,
            stopped_at=1704053600.0,
            status="failure",
            error_type="RuntimeError",
            error_message="WebSocket connection lost",
            duration_seconds=3600.0,
        ),
    ]


def build_error_records() -> tuple[list[HandlerErrorRecord | JobErrorRecord], list[HandlerErrorRecord]]:
    """Build app-tier and framework-tier error records.

    Returns:
        A ``(app_tier_errors, framework_tier_errors)`` tuple.
    """
    app_tier_errors = [
        HandlerErrorRecord(
            app_key="my_app",
            listener_id=42,
            handler_method="on_light_change",
            topic="state_changed.light.kitchen",
            execution_start_ts=1704067100.0,
            duration_ms=3.1,
            source_tier="app",
            error_type="ValueError",
            error_message="Bad state value",
        ),
        JobErrorRecord(
            app_key="my_app",
            job_id=7,
            handler_method="check_lights",
            job_name="check_lights",
            execution_start_ts=1704067000.0,
            duration_ms=4.2,
            source_tier="app",
            error_type="TimeoutError",
            error_message="Light service unavailable",
        ),
        HandlerErrorRecord(
            app_key="broken_app",
            listener_id=43,
            handler_method="on_door_open",
            topic="state_changed.binary_sensor.door",
            execution_start_ts=1704067050.0,
            duration_ms=10.0,
            source_tier="app",
            error_type="RuntimeError",
            error_message="Lock service timed out",
        ),
        # Orphan error — listener_id is None (handler was deleted)
        HandlerErrorRecord(
            app_key=None,
            listener_id=None,
            handler_method=None,
            topic=None,
            execution_start_ts=1704067000.5,
            duration_ms=1.0,
            source_tier="app",
            error_type="RuntimeError",
            error_message="Orphan error from deleted listener",
        ),
    ]
    framework_tier_errors = [
        HandlerErrorRecord(
            app_key="__hassette__.service_watcher",
            listener_id=999,
            handler_method="on_state_change_dispatch",
            topic="state_changed",
            execution_start_ts=1704067200.0,
            duration_ms=1.5,
            source_tier="framework",
            error_type="DispatchError",
            error_message="Framework dispatch failed",
        ),
    ]
    return app_tier_errors, framework_tier_errors


def build_global_summaries() -> tuple[GlobalSummary, GlobalSummary]:
    """Build framework-tier and default global summaries.

    Returns:
        A ``(framework_global_summary, default_global_summary)`` tuple.
    """
    framework_global_summary = GlobalSummary(
        listeners=ListenerGlobalStats(
            total_listeners=2,
            invoked_listeners=1,
            total_invocations=5,
            total_errors=1,
            total_di_failures=0,
            avg_duration_ms=1.5,
        ),
        jobs=JobGlobalStats(
            total_jobs=1,
            executed_jobs=1,
            total_executions=3,
            total_errors=0,
        ),
    )
    default_global_summary = GlobalSummary(
        listeners=ListenerGlobalStats(
            total_listeners=3,
            invoked_listeners=3,
            total_invocations=33,
            total_errors=3,
            total_di_failures=0,
            avg_duration_ms=2.5,
        ),
        jobs=JobGlobalStats(
            total_jobs=3,
            executed_jobs=3,
            total_executions=28,
            total_errors=6,
        ),
    )
    return framework_global_summary, default_global_summary


# ──────────────────────────────────────────────────────────────────────
# Telemetry wiring helpers
# ──────────────────────────────────────────────────────────────────────


def wire_listener_telemetry(hassette, listeners_by_app: dict[str, list[ListenerSummary]]) -> None:
    """Wire listener summary side effects onto the mock telemetry query service."""
    hassette._telemetry_query_service.get_listener_summary = AsyncMock(
        side_effect=lambda app_key, **_: listeners_by_app.get(app_key, [])
    )


def wire_job_telemetry(hassette, jobs_by_app: dict[str, list[JobSummary]]) -> None:
    """Wire job summary side effects onto the mock telemetry query service."""
    hassette._telemetry_query_service.get_job_summary = AsyncMock(
        side_effect=lambda app_key, **_: jobs_by_app.get(app_key, [])
    )


def wire_invocation_telemetry(
    hassette,
    handler_invocations: list[HandlerInvocation],
    job_executions: list[JobExecution],
) -> None:
    """Wire handler invocation and job execution records onto the mock telemetry query service."""
    hassette._telemetry_query_service.get_handler_invocations = AsyncMock(
        return_value=handler_invocations,
    )
    hassette._telemetry_query_service.get_job_executions = AsyncMock(
        return_value=job_executions,
    )


def build_app_health_summaries() -> dict[str, AppHealthSummary]:
    """Build per-app health summaries for e2e tests."""
    return {
        "my_app": AppHealthSummary(
            handler_count=2,
            job_count=2,
            total_invocations=30,
            total_errors=1,
            total_executions=20,
            total_job_errors=1,
            avg_duration_ms=2.0,
            last_activity_ts=1704067200.0,
        ),
        "broken_app": AppHealthSummary(
            handler_count=1,
            job_count=1,
            total_invocations=3,
            total_errors=2,
            total_executions=8,
            total_job_errors=5,
            avg_duration_ms=5.0,
            last_activity_ts=1704067050.0,
        ),
    }


def wire_app_health_summaries(hassette, summaries: dict[str, AppHealthSummary]) -> None:
    """Wire per-app health summaries onto the mock telemetry query service."""
    hassette._telemetry_query_service.get_all_app_summaries = AsyncMock(return_value=summaries)


def wire_session_telemetry(hassette, sessions: list[SessionRecord]) -> None:
    """Wire session list onto the mock telemetry query service."""
    hassette._telemetry_query_service.get_session_list = AsyncMock(return_value=sessions)


def wire_error_telemetry(
    hassette,
    app_tier_errors: list[HandlerErrorRecord | JobErrorRecord],
    framework_tier_errors: list[HandlerErrorRecord],
) -> None:
    """Wire error records with source_tier routing onto the mock telemetry query service."""

    def _make_errors_side_effect(source_tier: str = "all", **_kwargs):
        if source_tier == "framework":
            return framework_tier_errors
        if source_tier == "app":
            return app_tier_errors
        return app_tier_errors + framework_tier_errors

    hassette._telemetry_query_service.get_recent_errors = AsyncMock(
        side_effect=lambda **kwargs: _make_errors_side_effect(**kwargs)
    )


def wire_global_summary(
    hassette,
    framework_global_summary: GlobalSummary,
    default_global_summary: GlobalSummary,
) -> None:
    """Wire global summary and error count side effects onto the mock telemetry query service."""

    def _make_summary_side_effect(source_tier: str = "app", **_kwargs):
        if source_tier == "framework":
            return framework_global_summary
        return default_global_summary

    hassette._telemetry_query_service.get_global_summary = AsyncMock(
        side_effect=lambda **kwargs: _make_summary_side_effect(**kwargs)
    )

    def _make_error_counts_side_effect(source_tier: str = "app", **_kwargs) -> tuple[int, int]:
        if source_tier == "framework":
            return _FRAMEWORK_ERROR_COUNTS
        return (3, 6)

    hassette._telemetry_query_service.get_error_counts = AsyncMock(
        side_effect=lambda **kwargs: _make_error_counts_side_effect(**kwargs)
    )


def wire_owner_resolution(hassette) -> None:
    """Wire app instance owner resolution onto the mock app handler."""
    hassette._app_handler.registry.iter_all_instances.return_value = [
        ("my_app", 0, SimpleNamespace(unique_name="MyApp.MyApp[0]")),
    ]
    hassette._app_handler.registry.get_apps_by_key.return_value = {
        0: SimpleNamespace(unique_name="MyApp.MyApp[0]"),
    }
    hassette._app_handler.registry.get.side_effect = lambda app_key, index=0: (
        SimpleNamespace(unique_name="MyApp.MyApp[0]") if app_key == "my_app" and index == 0 else None
    )


# ──────────────────────────────────────────────────────────────────────
# Module-level computed constants for E2E assertions
#
# All constants are derived from the builder functions above — never
# hand-written literals.  Use these in E2E test assertions so that
# changing a seed value here automatically updates the tests.
#
# Naming convention: <TIER>_<ENTITY>_<FIELD>
#   APP_TIER_   — per-app health summaries (build_app_health_summaries)
#   GLOBAL_     — all-tier global summary (build_global_summaries)
#   ERRORS_     — error feed counts (build_error_records)
#   LISTENER_   — per-listener telemetry (build_listener_telemetry)
#   JOB_        — per-job telemetry (build_job_telemetry)
# ──────────────────────────────────────────────────────────────────────

# ── App-tier health summaries ──────────────────────────────────────────

_app_health = build_app_health_summaries()

APP_TIER_MY_APP_TOTAL_INVOCATIONS: int = _app_health["my_app"].total_invocations
APP_TIER_MY_APP_TOTAL_EXECUTIONS: int = _app_health["my_app"].total_executions
APP_TIER_BROKEN_APP_TOTAL_INVOCATIONS: int = _app_health["broken_app"].total_invocations
APP_TIER_BROKEN_APP_TOTAL_EXECUTIONS: int = _app_health["broken_app"].total_executions

# ── Global summary (default = app + framework combined denominator) ────

_framework_global_summary, _default_global_summary = build_global_summaries()

GLOBAL_TOTAL_INVOCATIONS: int = _default_global_summary.listeners.total_invocations
GLOBAL_TOTAL_EXECUTIONS: int = _default_global_summary.jobs.total_executions
GLOBAL_HANDLER_ERRORS: int = (
    _default_global_summary.listeners.total_errors + _default_global_summary.listeners.total_timed_out
)
GLOBAL_JOB_ERRORS: int = _default_global_summary.jobs.total_errors + _default_global_summary.jobs.total_timed_out
GLOBAL_TOTAL_FAILURES: int = GLOBAL_HANDLER_ERRORS + GLOBAL_JOB_ERRORS
GLOBAL_COMBINED_TOTAL: int = GLOBAL_TOTAL_INVOCATIONS + GLOBAL_TOTAL_EXECUTIONS

# ── Error feed counts ──────────────────────────────────────────────────

_app_tier_errors, _framework_tier_errors = build_error_records()

ERRORS_APP_TIER_COUNT: int = len(_app_tier_errors)
ERRORS_FRAMEWORK_TIER_COUNT: int = len(_framework_tier_errors)
ERRORS_COMBINED_COUNT: int = ERRORS_APP_TIER_COUNT + ERRORS_FRAMEWORK_TIER_COUNT

# Framework error counts derived from builder output — used by
# wire_global_summary to mock get_error_counts(source_tier="framework").
_FRAMEWORK_ERROR_COUNTS: tuple[int, int] = (
    sum(1 for e in _framework_tier_errors if isinstance(e, HandlerErrorRecord)),
    sum(1 for e in _framework_tier_errors if isinstance(e, JobErrorRecord)),
)
FRAMEWORK_TIER_TOTAL_HANDLER_ERRORS: int = _FRAMEWORK_ERROR_COUNTS[0]
FRAMEWORK_TIER_TOTAL_JOB_ERRORS: int = _FRAMEWORK_ERROR_COUNTS[1]

# ── Per-listener telemetry for my_app ─────────────────────────────────

_listeners = build_listener_telemetry()

LISTENER_MY_APP_1_TOTAL_INVOCATIONS: int = _listeners["my_app"][0].total_invocations
LISTENER_MY_APP_2_TOTAL_INVOCATIONS: int = _listeners["my_app"][1].total_invocations
LISTENER_MY_APP_1_SOURCE_LOCATION: str = _listeners["my_app"][0].source_location

# ── Per-job telemetry for my_app ───────────────────────────────────────

_jobs = build_job_telemetry()

JOB_MY_APP_1_TOTAL_EXECUTIONS: int = _jobs["my_app"][0].total_executions
JOB_MY_APP_2_TOTAL_EXECUTIONS: int = _jobs["my_app"][1].total_executions
JOB_MY_APP_1_SOURCE_LOCATION: str = _jobs["my_app"][0].source_location
