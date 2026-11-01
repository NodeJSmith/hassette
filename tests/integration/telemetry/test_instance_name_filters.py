"""Telemetry queries filter on the instance name, so history follows an instance when its config index changes."""

import time

from hassette.core.telemetry.query_service import TelemetryQueryService
from tests.integration.telemetry.helpers import (
    DbFixture,
    insert_execution,
    insert_invocation,
    insert_job,
    insert_listener,
    only_row,
    recent_activity,
    set_listener_retired_at,
)

FRAMEWORK_KEY = "__hassette__.BusService"


async def _two_instances_at_one_index(db: DbFixture) -> tuple[int, int]:
    """A listener with one run under each of two names, both stored at index 0 (as a reorder leaves old rows)."""
    db_svc, session_id = db
    upstairs = await insert_listener(db_svc, instance_name="upstairs", handler_method="on_upstairs")
    downstairs = await insert_listener(db_svc, instance_name="downstairs", handler_method="on_downstairs")
    await insert_invocation(db_svc, upstairs, session_id)
    await insert_invocation(db_svc, downstairs, session_id, status="error")
    return upstairs, downstairs


async def test_listener_summary_filters_by_name_not_index(query_service: TelemetryQueryService, db: DbFixture) -> None:
    await _two_instances_at_one_index(db)

    row = await only_row(query_service.get_listener_summary("test_app", "upstairs"))

    assert row.handler_method == "on_upstairs"


async def test_job_summary_filters_by_name_not_index(query_service: TelemetryQueryService, db: DbFixture) -> None:
    db_svc, _ = db
    await insert_job(db_svc, instance_name="upstairs", job_name="nightly")
    await insert_job(db_svc, instance_name="downstairs", job_name="hourly")

    row = await only_row(query_service.get_job_summary("test_app", "upstairs"))

    assert row.job_name == "nightly"


async def test_health_aggregates_filter_by_name(query_service: TelemetryQueryService, db: DbFixture) -> None:
    await _two_instances_at_one_index(db)

    upstairs = await query_service.get_app_health_aggregates("test_app", "upstairs")
    every_instance = await query_service.get_app_health_aggregates("test_app", None)

    assert (upstairs.total_invocations, upstairs.handler_errors) == (1, 0)
    assert (every_instance.total_invocations, every_instance.handler_errors) == (2, 1)


async def test_recent_activity_filters_by_name(query_service: TelemetryQueryService, db: DbFixture) -> None:
    db_svc, session_id = db
    await _two_instances_at_one_index(db)
    job_id = await insert_job(db_svc, instance_name="upstairs")
    await insert_execution(db_svc, job_id, session_id)

    entries = await recent_activity(query_service, instance_name="downstairs")

    assert [entry.handler_name for entry in entries] == ["on_downstairs"]
    assert len(await recent_activity(query_service, instance_name="upstairs")) == 2


async def test_a_name_with_no_rows_answers_empty_rather_than_another_instance(
    query_service: TelemetryQueryService, db: DbFixture
) -> None:
    """An index with no configured name resolves to a display label, which no stored row can hold."""
    await _two_instances_at_one_index(db)

    assert await query_service.get_listener_summary("test_app", "MyApp.7") == []
    assert (await query_service.get_app_health_aggregates("test_app", "MyApp.7")).total_invocations == 0


async def test_framework_rows_answer_without_a_name_filter(query_service: TelemetryQueryService, db: DbFixture) -> None:
    db_svc, session_id = db
    listener = await insert_listener(
        db_svc, instance_name="__hassette__", app_key=FRAMEWORK_KEY, handler_method="on_event", source_tier="framework"
    )
    await insert_invocation(db_svc, listener, session_id, source_tier="framework")

    row = await only_row(query_service.get_listener_summary(FRAMEWORK_KEY, None, source_tier="framework"))
    health = await query_service.get_app_health_aggregates(FRAMEWORK_KEY, None, source_tier="framework")

    assert row.listener_id == listener
    assert health.total_invocations == 1


async def test_retired_listeners_leave_summaries_but_their_runs_still_count(
    query_service: TelemetryQueryService, db: DbFixture
) -> None:
    """One row per handler after an upgrade or rename; health over a window reflects what ran in it."""
    db_svc, session_id = db
    retired = await insert_listener(db_svc, instance_name="__legacy__.0", handler_method="on_event", name="kitchen")
    live = await insert_listener(db_svc, instance_name="upstairs", handler_method="on_event", name="kitchen")
    await insert_invocation(db_svc, retired, session_id)
    await set_listener_retired_at(db_svc, retired, time.time())

    row = await only_row(query_service.get_listener_summary())
    health = await query_service.get_app_health_aggregates("test_app", None)

    assert row.listener_id == live
    assert health.total_invocations == 1
