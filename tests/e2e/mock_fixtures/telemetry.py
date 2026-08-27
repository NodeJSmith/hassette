"""Listener, job, execution, error, and summary telemetry builders for e2e mock data.

Each ``build_*`` is paired with its ``wire_*`` counterpart immediately below it, so seeding
one telemetry surface end-to-end (build the data, then wire it onto the mock query service)
reads top-to-bottom without jumping across the file.
"""

from collections.abc import Callable, Mapping
from typing import TypeVar
from unittest.mock import AsyncMock

from hassette.schemas.execution_models import Execution
from hassette.schemas.job_models import JobErrorRecord, JobGlobalStats, JobSummary
from hassette.schemas.listener_models import HandlerErrorRecord, ListenerGlobalStats, ListenerSummary
from hassette.schemas.summary_models import AppHealthSummary, GlobalSummary
from tests.e2e.mock_fixtures.constants import (
    APP_KEY_BROKEN_APP,
    APP_KEY_MY_APP,
    APP_KEY_NOSOURCE_APP,
    MANUAL_JOB_ID,
    TS_BASE,
    TS_OLDER,
    TS_OLDEST,
    TS_RECENT,
)

T = TypeVar("T")

# source_tier values the telemetry routes pass through to the query service.
FRAMEWORK_TIER = "framework"
APP_TIER = "app"
ALL_TIER = "all"

# get_error_counts() returns (handler_errors, job_errors); these are the non-framework totals.
DEFAULT_ERROR_COUNTS = (3, 6)


def by_app_key_or_all(items_by_app: Mapping[str, list[T]]) -> Callable[..., list[T]]:
    """Build a side effect that filters per-app telemetry rows by ``app_key``.

    Mirrors what the real query services do: no ``app_key`` means every app's rows, a known
    ``app_key`` means only that app's, and an unknown one means an empty list.
    """
    all_items = [item for items in items_by_app.values() for item in items]

    def side_effect(app_key: str | None = None, **_) -> list[T]:
        if app_key is None:
            return all_items
        return items_by_app.get(app_key, [])

    return side_effect


def by_tier(values: Mapping[str, T], *, default_tier: str, fallback: T) -> Callable[..., T]:
    """Build a side effect that routes on ``source_tier``.

    ``values`` maps a tier name to the rows served for it; any tier without an entry (including
    ``default_tier``, when the caller omits ``source_tier`` entirely) gets ``fallback``.
    """

    def side_effect(source_tier: str = default_tier, **_) -> T:
        return values.get(source_tier, fallback)

    return side_effect


def build_listener_telemetry() -> dict[str, list[ListenerSummary]]:
    """Build per-app listener summaries for e2e tests."""
    telemetry_listeners_my_app = [
        ListenerSummary(
            listener_id=1,
            handler_method="on_light_change",
            topic="state_changed.light.kitchen",
            app_key=APP_KEY_MY_APP,
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
            successful=8,
            failed=1,
            timed_out=1,
            di_failures=0,
            cancelled=0,
            total_duration_ms=20.0,
            avg_duration_ms=2.0,
            min_duration_ms=1.0,
            max_duration_ms=5.0,
            last_invoked_at=TS_BASE,
            last_error_type="ValueError",
            last_error_message="Bad state value",
        ),
        ListenerSummary(
            listener_id=2,
            handler_method="on_temp_update",
            topic="state_changed.sensor.temperature",
            app_key=APP_KEY_MY_APP,
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
            last_invoked_at=TS_RECENT,
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
            app_key=APP_KEY_BROKEN_APP,
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
            last_invoked_at=TS_OLDER,
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
            app_key=APP_KEY_NOSOURCE_APP,
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
            last_invoked_at=TS_OLDEST,
            last_error_type=None,
            last_error_message=None,
        ),
    ]
    return {
        APP_KEY_MY_APP: telemetry_listeners_my_app,
        APP_KEY_BROKEN_APP: telemetry_listeners_broken_app,
        APP_KEY_NOSOURCE_APP: telemetry_listeners_nosource_app,
    }


def wire_listener_telemetry(hassette, listeners_by_app: dict[str, list[ListenerSummary]]) -> None:
    """Wire listener summary side effects onto the mock telemetry query service."""
    hassette._telemetry_query_service.get_listener_summary = AsyncMock(side_effect=by_app_key_or_all(listeners_by_app))


def build_job_telemetry() -> dict[str, list[JobSummary]]:
    """Build per-app job summaries for e2e tests."""
    telemetry_jobs_my_app = [
        JobSummary(
            job_id=1,
            app_key=APP_KEY_MY_APP,
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
            last_executed_at=TS_BASE,
            total_duration_ms=52.5,
            avg_duration_ms=3.5,
        ),
        JobSummary(
            job_id=2,
            app_key=APP_KEY_MY_APP,
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
            last_executed_at=TS_RECENT,
            total_duration_ms=60.0,
            avg_duration_ms=12.0,
        ),
        # Manual-only job — no automatic trigger, submitted only via Run Now. Trigger
        # submission is wired via `wire_scheduler_trigger()` in mock_fixtures/scheduler.py.
        JobSummary(
            job_id=MANUAL_JOB_ID,
            app_key=APP_KEY_MY_APP,
            instance_index=0,
            job_name="send_notification",
            handler_method="send_notification",
            trigger_type=None,
            args_json="[]",
            kwargs_json="{}",
            source_location="my_app.py:60",
            registration_source="on_initialize",
            total_executions=0,
            successful=0,
            failed=0,
            last_executed_at=None,
            total_duration_ms=0.0,
            avg_duration_ms=0.0,
            schedule_status="manual",
        ),
    ]
    telemetry_jobs_broken_app = [
        JobSummary(
            job_id=3,
            app_key=APP_KEY_BROKEN_APP,
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
            last_executed_at=TS_OLDER,
            total_duration_ms=64.0,
            avg_duration_ms=8.0,
        ),
    ]
    # nosource_app jobs — empty source fields for testing hidden source display.
    telemetry_jobs_nosource_app = [
        JobSummary(
            job_id=100,
            app_key=APP_KEY_NOSOURCE_APP,
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
            last_executed_at=TS_OLDEST,
            total_duration_ms=2.0,
            avg_duration_ms=1.0,
        ),
    ]
    return {
        APP_KEY_MY_APP: telemetry_jobs_my_app,
        APP_KEY_BROKEN_APP: telemetry_jobs_broken_app,
        APP_KEY_NOSOURCE_APP: telemetry_jobs_nosource_app,
    }


def wire_job_telemetry(hassette, jobs_by_app: dict[str, list[JobSummary]]) -> None:
    """Wire job summary side effects onto the mock telemetry query service."""
    hassette._telemetry_query_service.get_job_summary = AsyncMock(side_effect=by_app_key_or_all(jobs_by_app))


def build_executions() -> list[Execution]:
    """Build unified execution records for e2e drill-down tests.

    Returns a mix of handler (kind='handler') and job (kind='job') records to seed
    the ``/telemetry/listener/{id}/executions`` and ``/telemetry/job/{id}/executions``
    endpoints served by ``wire_invocation_telemetry``.
    """
    return [
        Execution(
            kind="handler",
            listener_id=1,
            execution_start_ts=TS_BASE,
            duration_ms=2.5,
            status="success",
            error_type=None,
            error_message=None,
            error_traceback=None,
        ),
        Execution(
            kind="handler",
            listener_id=1,
            execution_start_ts=TS_RECENT,
            duration_ms=3.1,
            status="error",
            error_type="ValueError",
            error_message="Bad state value",
            error_traceback=(
                'Traceback (most recent call last):\n  File "my_app.py", line 18, in '
                'on_light_change\n    raise ValueError("Bad state value")\nValueError: Bad state value\n'
            ),
        ),
        Execution(
            kind="job",
            job_id=7,
            execution_start_ts=TS_BASE,
            duration_ms=3.0,
            status="success",
            error_type=None,
            error_message=None,
        ),
        Execution(
            kind="job",
            job_id=7,
            execution_start_ts=TS_RECENT,
            duration_ms=4.2,
            status="error",
            error_type="TimeoutError",
            error_message="Light service unavailable",
        ),
    ]


def wire_invocation_telemetry(hassette, executions: list[Execution]) -> None:
    """Wire unified execution records onto the mock telemetry query service.

    Wires ``get_executions`` to serve all records, filtered by ``listener_id``,
    ``job_id``, or ``kind`` when those keyword arguments are provided.  This
    matches the signature called by all three web-route handlers
    (``/telemetry/executions``, ``/telemetry/listener/{id}/executions``,
    ``/telemetry/job/{id}/executions``).
    """

    def _executions_side_effect(
        *,
        listener_id: int | None = None,
        job_id: int | None = None,
        kind: str | None = None,
        limit: int = 50,
        since: float | None = None,
    ) -> list[Execution]:
        rows = executions
        if listener_id is not None:
            rows = [e for e in rows if e.listener_id == listener_id]
        if job_id is not None:
            rows = [e for e in rows if e.job_id == job_id]
        if kind is not None:
            rows = [e for e in rows if e.kind == kind]
        if since is not None:
            rows = [e for e in rows if e.execution_start_ts >= since]
        return rows[:limit]

    hassette._telemetry_query_service.get_executions = AsyncMock(side_effect=_executions_side_effect)


def build_error_records() -> tuple[list[HandlerErrorRecord | JobErrorRecord], list[HandlerErrorRecord]]:
    """Build app-tier and framework-tier error records.

    Returns:
        A ``(app_tier_errors, framework_tier_errors)`` tuple.
    """
    app_tier_errors = [
        HandlerErrorRecord(
            app_key=APP_KEY_MY_APP,
            listener_id=42,
            handler_method="on_light_change",
            topic="state_changed.light.kitchen",
            execution_start_ts=TS_RECENT,
            duration_ms=3.1,
            source_tier="app",
            error_type="ValueError",
            error_message="Bad state value",
        ),
        JobErrorRecord(
            app_key=APP_KEY_MY_APP,
            job_id=7,
            handler_method="check_lights",
            job_name="check_lights",
            execution_start_ts=TS_OLDEST,
            duration_ms=4.2,
            source_tier="app",
            error_type="TimeoutError",
            error_message="Light service unavailable",
        ),
        HandlerErrorRecord(
            app_key=APP_KEY_BROKEN_APP,
            listener_id=43,
            handler_method="on_door_open",
            topic="state_changed.binary_sensor.door",
            execution_start_ts=TS_OLDER,
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
            execution_start_ts=TS_OLDEST + 0.5,
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
            execution_start_ts=TS_BASE,
            duration_ms=1.5,
            source_tier="framework",
            error_type="DispatchError",
            error_message="Framework dispatch failed",
        ),
    ]
    return app_tier_errors, framework_tier_errors


def wire_error_telemetry(
    hassette,
    app_tier_errors: list[HandlerErrorRecord | JobErrorRecord],
    framework_tier_errors: list[HandlerErrorRecord],
) -> None:
    """Wire error records with source_tier routing onto the mock telemetry query service."""
    hassette._telemetry_query_service.get_recent_errors = AsyncMock(
        side_effect=by_tier(
            {FRAMEWORK_TIER: framework_tier_errors, APP_TIER: app_tier_errors},
            default_tier=ALL_TIER,
            fallback=app_tier_errors + framework_tier_errors,
        )
    )


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


def wire_global_summary(
    hassette,
    framework_global_summary: GlobalSummary,
    default_global_summary: GlobalSummary,
    framework_tier_errors: list[HandlerErrorRecord] | None = None,
) -> None:
    """Wire global summary and error count side effects onto the mock telemetry query service."""
    hassette._telemetry_query_service.get_global_summary = AsyncMock(
        side_effect=by_tier(
            {FRAMEWORK_TIER: framework_global_summary},
            default_tier=APP_TIER,
            fallback=default_global_summary,
        )
    )

    fw_errors = framework_tier_errors or []
    framework_error_counts = (
        sum(1 for e in fw_errors if isinstance(e, HandlerErrorRecord)),
        sum(1 for e in fw_errors if isinstance(e, JobErrorRecord)),
    )
    hassette._telemetry_query_service.get_error_counts = AsyncMock(
        side_effect=by_tier(
            {FRAMEWORK_TIER: framework_error_counts},
            default_tier=APP_TIER,
            fallback=DEFAULT_ERROR_COUNTS,
        )
    )


def build_app_health_summaries() -> dict[str, AppHealthSummary]:
    """Build per-app health summaries for e2e tests."""
    return {
        APP_KEY_MY_APP: AppHealthSummary(
            handler_count=2,
            job_count=2,
            total_invocations=30,
            total_errors=1,
            total_executions=20,
            total_job_errors=1,
            avg_duration_ms=2.0,
            last_activity_ts=TS_BASE,
        ),
        APP_KEY_BROKEN_APP: AppHealthSummary(
            handler_count=1,
            job_count=1,
            total_invocations=3,
            total_errors=2,
            total_executions=8,
            total_job_errors=5,
            avg_duration_ms=5.0,
            last_activity_ts=TS_OLDER,
        ),
    }


def wire_app_health_summaries(hassette, summaries: dict[str, AppHealthSummary]) -> None:
    """Wire per-app health summaries onto the mock telemetry query service."""
    hassette._telemetry_query_service.get_all_app_summaries = AsyncMock(return_value=summaries)
