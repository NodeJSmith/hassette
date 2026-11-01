"""Integration tests for get_log_records filter clauses (summary_queries.py).

Covers the execution_id, author, level, since, app_key, and instance_name filter branches
that are uncovered by the web API mock layer.
"""

import itertools
import time

import pytest
from hassette_wire import LogAuthor

from hassette.core.database_service import DatabaseService
from hassette.core.telemetry.query_service import TelemetryQueryService

from .helpers import DbFixture, insert_listener

SEQ_COUNTER = itertools.count(1)


async def insert_log_record(
    db_svc: DatabaseService,
    *,
    app_key: str = "test_app",
    level: str = "INFO",
    execution_id: str | None = None,
    author: LogAuthor = "app",
    instance_index: int = 0,
    timestamp: float | None = None,
    message: str = "test message",
) -> None:
    ts = timestamp if timestamp is not None else time.time()
    await db_svc.db.execute(
        """INSERT INTO log_records
               (seq, timestamp, level, logger_name, func_name, lineno, message,
                exc_info, app_key, instance_name, instance_index, execution_id, author)
           VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)""",
        (
            next(SEQ_COUNTER),
            ts,
            level,
            "hassette.test",
            "test_fn",
            1,
            message,
            app_key,
            f"instance_{instance_index}",
            instance_index,
            execution_id,
            author,
        ),
    )
    await db_svc.db.commit()


class TestGetLogRecordsFilters:
    async def test_filter_by_execution_id(self, db: DbFixture, query_service: TelemetryQueryService) -> None:
        db_svc, _ = db
        await insert_log_record(db_svc, execution_id="exec-aaa", message="match")
        await insert_log_record(db_svc, execution_id="exec-bbb", message="other")
        await insert_log_record(db_svc, execution_id=None, message="none")

        results = await query_service.get_log_records(execution_id="exec-aaa")

        assert len(results) == 1
        assert results[0]["message"] == "match"
        assert results[0]["execution_id"] == "exec-aaa"

    async def test_author_all_applies_no_filter(self, db: DbFixture, query_service: TelemetryQueryService) -> None:
        db_svc, _ = db
        await insert_log_record(db_svc, author="framework", message="fw")
        await insert_log_record(db_svc, author="app", message="app")

        results = await query_service.get_log_records(author="all")

        assert {r["message"] for r in results} == {"fw", "app"}

    @pytest.mark.parametrize("author", ["app", "framework"])
    async def test_filter_by_author(
        self, db: DbFixture, query_service: TelemetryQueryService, author: LogAuthor
    ) -> None:
        db_svc, _ = db
        await insert_log_record(db_svc, author="framework", level="ERROR", message="framework")
        await insert_log_record(db_svc, author="app", level="DEBUG", message="app")

        results = await query_service.get_log_records(author=author)

        assert [(r["message"], r["author"]) for r in results] == [(author, author)]

    async def test_default_keeps_app_lines_and_framework_errors(
        self, db: DbFixture, query_service: TelemetryQueryService
    ) -> None:
        """No author: every app line, plus framework lines at ERROR and above."""
        db_svc, _ = db
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            await insert_log_record(db_svc, author="app", level=level, message=f"app {level}")
            await insert_log_record(db_svc, author="framework", level=level, message=f"framework {level}")

        results = await query_service.get_log_records()

        assert {r["message"] for r in results} == {
            "app DEBUG",
            "app INFO",
            "app WARNING",
            "app ERROR",
            "app CRITICAL",
            "framework ERROR",
            "framework CRITICAL",
        }

    async def test_default_filters_before_the_limit(self, db: DbFixture, query_service: TelemetryQueryService) -> None:
        """Hidden framework lines never use up the row cap, even when they are the newest rows."""
        db_svc, _ = db
        now = time.time()
        await insert_log_record(db_svc, author="app", timestamp=now - 100, message="older app line")
        for i in range(5):
            await insert_log_record(db_svc, author="framework", level="DEBUG", timestamp=now - i, message="noise")

        results = await query_service.get_log_records(limit=1)

        assert [r["message"] for r in results] == ["older app line"]

    async def test_filter_by_level(self, db: DbFixture, query_service: TelemetryQueryService) -> None:
        db_svc, _ = db
        await insert_log_record(db_svc, level="ERROR", message="err")
        await insert_log_record(db_svc, level="INFO", message="info")
        await insert_log_record(db_svc, level="WARNING", message="warn")

        results = await query_service.get_log_records(level="ERROR")

        assert len(results) == 1
        assert results[0]["message"] == "err"
        assert results[0]["level"] == "ERROR"

    async def test_filter_by_since(self, db: DbFixture, query_service: TelemetryQueryService) -> None:
        db_svc, _ = db
        old_ts = 1_000_000.0
        new_ts = 2_000_000.0
        await insert_log_record(db_svc, timestamp=old_ts, message="old")
        await insert_log_record(db_svc, timestamp=new_ts, message="new")

        results = await query_service.get_log_records(since=1_500_000.0)

        assert len(results) == 1
        assert results[0]["message"] == "new"

    async def test_filter_by_app_key(self, db: DbFixture, query_service: TelemetryQueryService) -> None:
        db_svc, _ = db
        await insert_log_record(db_svc, app_key="app_a", message="a")
        await insert_log_record(db_svc, app_key="app_b", message="b")

        results = await query_service.get_log_records(app_key="app_a")

        assert len(results) == 1
        assert results[0]["message"] == "a"

    async def test_filter_by_instance_name(self, db: DbFixture, query_service: TelemetryQueryService) -> None:
        db_svc, _ = db
        await insert_log_record(db_svc, app_key="multi", instance_index=0, message="zero")
        await insert_log_record(db_svc, app_key="multi", instance_index=1, message="one")

        filtered = await query_service.get_log_records(app_key="multi", instance_name="instance_1")
        unfiltered = await query_service.get_log_records(app_key="multi")

        assert [(r["message"], r["instance_index"]) for r in filtered] == [("one", 1)]
        assert {r["message"] for r in unfiltered} == {"zero", "one"}

    async def test_combined_filters(self, db: DbFixture, query_service: TelemetryQueryService) -> None:
        db_svc, _ = db
        await insert_log_record(db_svc, app_key="my_app", level="ERROR", execution_id="exec-1", message="target")
        await insert_log_record(db_svc, app_key="my_app", level="INFO", execution_id="exec-1", message="wrong level")
        await insert_log_record(db_svc, app_key="other", level="ERROR", execution_id="exec-1", message="wrong app")

        results = await query_service.get_log_records(app_key="my_app", level="ERROR", execution_id="exec-1")

        assert len(results) == 1
        assert results[0]["message"] == "target"

    async def test_joins_execution_kind_from_executions_table(
        self, db: DbFixture, query_service: TelemetryQueryService
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

    async def test_no_filters_returns_all(self, db: DbFixture, query_service: TelemetryQueryService) -> None:
        db_svc, _ = db
        await insert_log_record(db_svc, message="one")
        await insert_log_record(db_svc, message="two")

        results = await query_service.get_log_records()

        assert len(results) >= 2
