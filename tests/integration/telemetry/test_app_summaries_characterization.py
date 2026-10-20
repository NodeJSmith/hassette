"""Characterization pin for get_all_app_summaries().

Seeds one fixed dataset spanning app/framework tiers, multi-instance registrations, an idle app,
skipped/timed-out runs, and records on both sides of a ``since`` cutoff, then pins the full output
for every source tier with and without ``since``. Any restructuring of the query construction or
the batched read transaction must keep these outputs identical.
"""

from typing import Any

import aiosqlite
import pytest
from hassette_wire import QuerySourceTier

from hassette.core.telemetry.query_service import TelemetryQueryService
from hassette.exceptions import TelemetryUnavailableError
from hassette.utils.aiosqlite_utils import connect_daemon

from .helpers import BASE_TS, DbFixture, insert_execution, insert_invocation, insert_job, insert_listener

SINCE_TS = BASE_TS + 5.0


async def seed_dataset(db: DbFixture) -> None:
    db_svc, session_id = db

    # app_a: one handler identity registered on two instances, plus one job.
    a_l0 = await insert_listener(db_svc, app_key="app_a", instance_index=0, name="on_a")
    a_l1 = await insert_listener(db_svc, app_key="app_a", instance_index=1, name="on_a")
    a_job = await insert_job(db_svc, app_key="app_a", job_name="job_a")
    await insert_invocation(
        db_svc, a_l0, session_id, status="success", duration_ms=10.0, execution_start_ts=BASE_TS + 10
    )
    await insert_invocation(db_svc, a_l1, session_id, status="error", duration_ms=30.0, execution_start_ts=BASE_TS + 20)
    await insert_invocation(
        db_svc, a_l0, session_id, status="timed_out", duration_ms=20.0, execution_start_ts=BASE_TS + 1
    )
    await insert_execution(
        db_svc, a_job, session_id, status="success", duration_ms=100.0, execution_start_ts=BASE_TS + 15
    )
    await insert_execution(
        db_svc, a_job, session_id, status="skipped", duration_ms=0.0, execution_start_ts=BASE_TS + 16
    )
    await insert_execution(db_svc, a_job, session_id, status="error", duration_ms=50.0, execution_start_ts=BASE_TS + 2)

    # app_b: an app-tier and a framework-tier listener under the same app key.
    b_app = await insert_listener(db_svc, app_key="app_b", name="on_b")
    b_fw = await insert_listener(db_svc, app_key="app_b", name="on_b_fw", source_tier="framework")
    await insert_invocation(db_svc, b_app, session_id, duration_ms=4.0, execution_start_ts=BASE_TS + 12)
    await insert_invocation(
        db_svc,
        b_fw,
        session_id,
        status="error",
        duration_ms=8.0,
        execution_start_ts=BASE_TS + 13,
        source_tier="framework",
    )

    # app_idle: registered but never ran.
    await insert_listener(db_svc, app_key="app_idle", name="on_idle")

    # __hassette__: framework-only job.
    fw_job = await insert_job(db_svc, app_key="__hassette__", job_name="fw_job", source_tier="framework")
    await insert_execution(
        db_svc,
        fw_job,
        session_id,
        status="timed_out",
        duration_ms=7.0,
        execution_start_ts=BASE_TS + 3,
        source_tier="framework",
    )


def summary(
    handler_count: int,
    job_count: int,
    **aggregates: Any,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "total_invocations": 0,
        "handler_errors": 0,
        "handler_timed_out": 0,
        "handler_avg_duration_ms": None,
        "total_executions": 0,
        "job_errors": 0,
        "job_timed_out": 0,
        "job_avg_duration_ms": None,
        "last_activity_ts": None,
    }
    return {"handler_count": handler_count, "job_count": job_count, "aggregates": {**base, **aggregates}}


@pytest.mark.usefixtures("db")
async def test_empty_db_returns_no_summaries(query_service: TelemetryQueryService) -> None:
    for tier in ("app", "framework", "all"):
        assert await query_service.get_all_app_summaries(source_tier=tier) == {}
        assert await query_service.get_all_app_summaries(since=SINCE_TS, source_tier=tier) == {}


A_ALL_TIME = summary(
    1,
    1,
    total_invocations=3,
    handler_errors=1,
    handler_timed_out=1,
    handler_avg_duration_ms=20.0,
    total_executions=3,
    job_errors=1,
    job_avg_duration_ms=75.0,
    last_activity_ts=BASE_TS + 20,
)
A_SINCE = summary(
    1,
    1,
    total_invocations=2,
    handler_errors=1,
    handler_avg_duration_ms=20.0,
    total_executions=2,
    job_avg_duration_ms=100.0,
    last_activity_ts=BASE_TS + 20,
)
B_APP = summary(1, 0, total_invocations=1, handler_avg_duration_ms=4.0, last_activity_ts=BASE_TS + 12)
B_FRAMEWORK = summary(
    1, 0, total_invocations=1, handler_errors=1, handler_avg_duration_ms=8.0, last_activity_ts=BASE_TS + 13
)
B_ALL = summary(2, 0, total_invocations=2, handler_errors=1, handler_avg_duration_ms=6.0, last_activity_ts=BASE_TS + 13)
IDLE = summary(1, 0)
FW_ALL_TIME = summary(0, 1, total_executions=1, job_timed_out=1, job_avg_duration_ms=7.0, last_activity_ts=BASE_TS + 3)
FW_SINCE = summary(0, 1)

PINNED: list[tuple[QuerySourceTier, float | None, dict[str, dict[str, Any]]]] = [
    ("app", None, {"app_a": A_ALL_TIME, "app_b": B_APP, "app_idle": IDLE}),
    ("app", SINCE_TS, {"app_a": A_SINCE, "app_b": B_APP, "app_idle": IDLE}),
    ("framework", None, {"app_b": B_FRAMEWORK, "__hassette__": FW_ALL_TIME}),
    ("framework", SINCE_TS, {"app_b": B_FRAMEWORK, "__hassette__": FW_SINCE}),
    ("all", None, {"app_a": A_ALL_TIME, "app_b": B_ALL, "app_idle": IDLE, "__hassette__": FW_ALL_TIME}),
    ("all", SINCE_TS, {"app_a": A_SINCE, "app_b": B_ALL, "app_idle": IDLE, "__hassette__": FW_SINCE}),
]


@pytest.mark.parametrize(("source_tier", "since", "expected"), PINNED)
async def test_pinned_output(
    query_service: TelemetryQueryService,
    db: DbFixture,
    source_tier: QuerySourceTier,
    since: float | None,
    expected: dict[str, dict[str, Any]],
) -> None:
    await seed_dataset(db)
    result = await query_service.get_all_app_summaries(since=since, source_tier=source_tier)
    assert {key: value.model_dump() for key, value in result.items()} == expected


async def test_storage_error_raises_telemetry_unavailable(query_service: TelemetryQueryService, db: DbFixture) -> None:
    """A storage failure inside the snapshot read surfaces as TelemetryUnavailableError and frees the lock."""
    db_svc, _ = db
    await db_svc._read_db.close()
    try:
        with pytest.raises(TelemetryUnavailableError):
            await query_service.get_all_app_summaries()
        assert not query_service._snapshot_lock.locked()
    finally:
        # Restore so fixture teardown doesn't crash.
        db_svc._read_db = await connect_daemon(db_svc._db_path, isolation_level=None)
        db_svc._read_db.row_factory = aiosqlite.Row


async def test_failure_after_begin_rolls_back_snapshot(query_service: TelemetryQueryService, db: DbFixture) -> None:
    """A query failing mid-snapshot raises TelemetryUnavailableError and leaves no transaction open."""
    await seed_dataset(db)
    with pytest.raises(TelemetryUnavailableError):
        await query_service._read_summary_snapshot([("SELECT 1", None), ("SELECT * FROM no_such_table", None)])

    assert not query_service._db.in_transaction
    assert not query_service._snapshot_lock.locked()
    # A leaked transaction would make the next BEGIN DEFERRED fail; the next read must succeed.
    assert await query_service.get_all_app_summaries()
