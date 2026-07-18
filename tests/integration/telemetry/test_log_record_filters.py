"""Integration tests for get_log_records filter clauses (summary_queries.py).

Covers the execution_id, source_tier, level, since, and app_key filter branches
that are uncovered by the web API mock layer.
"""

import time

from hassette.core.database_service import DatabaseService
from hassette.core.telemetry.query_service import TelemetryQueryService

from .helpers import insert_listener

SEQ_COUNTER = 0


async def insert_log_record(
    db_svc: DatabaseService,
    *,
    app_key: str = "test_app",
    level: str = "INFO",
    execution_id: str | None = None,
    source_tier: str = "app",
    timestamp: float | None = None,
    message: str = "test message",
) -> None:
    global SEQ_COUNTER
    SEQ_COUNTER += 1
    ts = timestamp if timestamp is not None else time.time()
    await db_svc.db.execute(
        """INSERT INTO log_records
               (seq, timestamp, level, logger_name, func_name, lineno, message,
                exc_info, app_key, instance_name, instance_index, execution_id, source_tier)
           VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, 0, ?, ?)""",
        (SEQ_COUNTER, ts, level, "hassette.test", "test_fn", 1, message, app_key, execution_id, source_tier),
    )
    await db_svc.db.commit()


class TestGetLogRecordsFilters:
    async def test_filter_by_execution_id(
        self, db: tuple[DatabaseService, int], query_service: TelemetryQueryService
    ) -> None:
        db_svc, _ = db
        await insert_log_record(db_svc, execution_id="exec-aaa", message="match")
        await insert_log_record(db_svc, execution_id="exec-bbb", message="other")
        await insert_log_record(db_svc, execution_id=None, message="none")

        results = await query_service.get_log_records(execution_id="exec-aaa")

        assert len(results) == 1
        assert results[0]["message"] == "match"
        assert results[0]["execution_id"] == "exec-aaa"

    async def test_filter_by_source_tier(
        self, db: tuple[DatabaseService, int], query_service: TelemetryQueryService
    ) -> None:
        db_svc, _ = db
        await insert_log_record(db_svc, source_tier="framework", message="fw")
        await insert_log_record(db_svc, source_tier="app", message="app")

        results = await query_service.get_log_records(source_tier="framework")

        assert len(results) == 1
        assert results[0]["message"] == "fw"
        assert results[0]["source_tier"] == "framework"

    async def test_filter_by_level(self, db: tuple[DatabaseService, int], query_service: TelemetryQueryService) -> None:
        db_svc, _ = db
        await insert_log_record(db_svc, level="ERROR", message="err")
        await insert_log_record(db_svc, level="INFO", message="info")
        await insert_log_record(db_svc, level="WARNING", message="warn")

        results = await query_service.get_log_records(level="ERROR")

        assert len(results) == 1
        assert results[0]["message"] == "err"
        assert results[0]["level"] == "ERROR"

    async def test_filter_by_since(self, db: tuple[DatabaseService, int], query_service: TelemetryQueryService) -> None:
        db_svc, _ = db
        old_ts = 1_000_000.0
        new_ts = 2_000_000.0
        await insert_log_record(db_svc, timestamp=old_ts, message="old")
        await insert_log_record(db_svc, timestamp=new_ts, message="new")

        results = await query_service.get_log_records(since=1_500_000.0)

        assert len(results) == 1
        assert results[0]["message"] == "new"

    async def test_filter_by_app_key(
        self, db: tuple[DatabaseService, int], query_service: TelemetryQueryService
    ) -> None:
        db_svc, _ = db
        await insert_log_record(db_svc, app_key="app_a", message="a")
        await insert_log_record(db_svc, app_key="app_b", message="b")

        results = await query_service.get_log_records(app_key="app_a")

        assert len(results) == 1
        assert results[0]["message"] == "a"

    async def test_combined_filters(
        self, db: tuple[DatabaseService, int], query_service: TelemetryQueryService
    ) -> None:
        db_svc, _ = db
        await insert_log_record(db_svc, app_key="my_app", level="ERROR", execution_id="exec-1", message="target")
        await insert_log_record(db_svc, app_key="my_app", level="INFO", execution_id="exec-1", message="wrong level")
        await insert_log_record(db_svc, app_key="other", level="ERROR", execution_id="exec-1", message="wrong app")

        results = await query_service.get_log_records(app_key="my_app", level="ERROR", execution_id="exec-1")

        assert len(results) == 1
        assert results[0]["message"] == "target"

    async def test_joins_execution_kind_from_executions_table(
        self, db: tuple[DatabaseService, int], query_service: TelemetryQueryService
    ) -> None:
        """Log records JOIN executions to get execution_kind, listener_id, job_id."""
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc)
        # Insert an execution row so the JOIN has something to match
        await db_svc.db.execute(
            """INSERT INTO executions
                   (kind, listener_id, session_id, execution_start_ts, duration_ms, status,
                    source_tier, execution_id)
               VALUES ('handler', ?, ?, ?, 10.0, 'success', 'app', 'exec-join-test')""",
            (listener_id, session_id, time.time()),
        )
        await db_svc.db.commit()
        await insert_log_record(db_svc, execution_id="exec-join-test", message="with join")

        results = await query_service.get_log_records(execution_id="exec-join-test")

        assert len(results) == 1
        assert results[0]["execution_kind"] == "handler"
        assert results[0]["listener_id"] == listener_id

    async def test_no_filters_returns_all(
        self, db: tuple[DatabaseService, int], query_service: TelemetryQueryService
    ) -> None:
        db_svc, _ = db
        await insert_log_record(db_svc, message="one")
        await insert_log_record(db_svc, message="two")

        results = await query_service.get_log_records()

        assert len(results) >= 2
