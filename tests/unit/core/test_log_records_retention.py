"""Unit tests for log_records retention, size failsafe priority ordering, and LogPersistenceHandler wiring."""

import asyncio
import logging
import sqlite3
import time
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import aiosqlite
import pytest

from hassette.const.misc import SECONDS_PER_DAY
from hassette.core.database_service import DatabaseService
from hassette.logging_ import LogPersistenceHandler
from hassette.utils.aiosqlite_utils import connect_daemon
from tests.support.helpers import DB_HASSETTE_RESOURCE_SHUTDOWN_TIMEOUT_SECONDS, DB_HASSETTE_TELEMETRY_WRITE_QUEUE_MAX
from tests.support.mock_hassette import make_mock_hassette

from .conftest import TELEMETRY_TEST_DDL as DDL

SOURCE_TIER_FRAMEWORK = "framework"
SOURCE_TIER_APP = "app"


def make_log_record_row(seq: int, timestamp: float, message: str) -> dict[str, Any]:
    """Build a log_records row dict with fixed metadata fields; only seq/timestamp/message vary.

    ``lineno`` mirrors ``seq`` — every call site in this file already uses the same value for
    both.
    """
    return {
        "seq": seq,
        "timestamp": timestamp,
        "level": "INFO",
        "logger_name": "x",
        "func_name": "f",
        "lineno": seq,
        "message": message,
        "exc_info": None,
        "app_key": "a",
        "instance_name": "a_0",
        "instance_index": 0,
        "execution_id": None,
        "source_tier": SOURCE_TIER_APP,
    }


@pytest.fixture
def mock_hassette_for_db(tmp_path: Path) -> MagicMock:
    """Mock Hassette for DatabaseService tests."""
    return make_mock_hassette(
        data_dir=tmp_path,
        set_ready=False,
        database={"telemetry_write_queue_max": DB_HASSETTE_TELEMETRY_WRITE_QUEUE_MAX},
        lifecycle={"resource_shutdown_timeout_seconds": DB_HASSETTE_RESOURCE_SHUTDOWN_TIMEOUT_SECONDS},
    )


@pytest.fixture
async def db() -> aiosqlite.Connection:
    """In-memory aiosqlite connection with log_records schema."""
    conn = await connect_daemon(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.executescript(DDL)
    try:
        yield conn
    finally:
        await conn.close()


async def insert_tiered_execution(db: aiosqlite.Connection, timestamp: float, source_tier: str) -> None:
    """Insert a minimal executions row with an explicit source_tier.

    ``insert_execution_row()`` (``tests/support/sql.py``) deliberately omits ``source_tier`` and
    relies on the schema default — not usable here since tier-aware retention tests need rows in
    both tiers.

    Always ``kind='handler'``, so ``listener_id`` is set to a placeholder id (foreign key
    enforcement is off in these tests) to satisfy the production
    ``CHECK ((listener_id IS NOT NULL) + (job_id IS NOT NULL) = 1)`` constraint now mirrored in
    the unit test DDL.
    """
    await db.execute(
        "INSERT INTO executions (kind, listener_id, execution_start_ts, source_tier) VALUES ('handler', 1, ?, ?)",
        (timestamp, source_tier),
    )


async def insert_blocking_event(db: aiosqlite.Connection, detected_ts: float) -> None:
    """Insert a minimal blocking_events row (tier='watchdog', source_tier=app)."""
    await db.execute(
        "INSERT INTO blocking_events (tier, detected_ts, source_tier) VALUES ('watchdog', ?, 'app')",
        (detected_ts,),
    )


def make_failing_execute(db: aiosqlite.Connection, fail_on: str) -> Callable[..., Coroutine[Any, Any, Any]]:
    """Build a ``db.execute`` replacement that raises on the first SQL statement containing
    ``fail_on``, delegating everything else to the real ``db.execute``.

    Shared by the per-target failure isolation tests below, which each simulate one target's
    DELETE raising ``sqlite3.OperationalError`` to verify the others still commit independently.
    """
    original_execute = db.execute

    async def failing_execute(sql: str, *args: Any, **kwargs: Any) -> Any:
        if fail_on in sql:
            raise sqlite3.OperationalError("simulated failure")
        return await original_execute(sql, *args, **kwargs)

    return failing_execute


@pytest.fixture
def db_service_writer(db: aiosqlite.Connection) -> DatabaseService:
    """DatabaseService with an in-memory test DB connection for seeding records."""
    mock_hassette = MagicMock()
    svc = DatabaseService.__new__(DatabaseService)
    svc.hassette = mock_hassette
    svc._db = db  # pyright: ignore[reportPrivateUsage]
    return svc


@pytest.fixture
def retention_service(db: aiosqlite.Connection, mock_hassette_for_db: MagicMock) -> DatabaseService:
    """Real DatabaseService wired to the in-memory test DB, for retention/failsafe cleanup tests."""
    svc = DatabaseService(mock_hassette_for_db, parent=None)
    svc._db = db  # pyright: ignore[reportPrivateUsage]
    return svc


class TestRetentionCleanup:
    async def test_retention_deletes_old_log_records(
        self,
        db: aiosqlite.Connection,
        db_service_writer: DatabaseService,
        retention_service: DatabaseService,
    ) -> None:
        """_do_run_retention_cleanup() deletes log_records older than log_retention_days."""
        # Seed: one old record (5 days ago), one recent (now)
        now = time.time()
        old_ts = now - (5 * SECONDS_PER_DAY)  # 5 days ago (older than log_retention_days=3)
        recent_ts = now - (1 * SECONDS_PER_DAY)  # 1 day ago (within log_retention_days=3)

        await db_service_writer._insert_log_records(  # pyright: ignore[reportPrivateUsage]
            [
                make_log_record_row(1, old_ts, "old"),
                make_log_record_row(2, recent_ts, "recent"),
            ],
        )

        await retention_service._do_run_retention_cleanup()  # pyright: ignore[reportPrivateUsage]

        cursor = await db.execute("SELECT message FROM log_records ORDER BY seq")
        remaining = [row[0] for row in await cursor.fetchall()]
        assert remaining == ["recent"]

    async def test_retention_keeps_within_log_retention_days(
        self,
        db: aiosqlite.Connection,
        db_service_writer: DatabaseService,
        retention_service: DatabaseService,
    ) -> None:
        """Retention cleanup keeps records within log_retention_days."""
        now = time.time()
        # Use half-day offsets to avoid exact boundary ambiguity with log_retention_days=3:
        # 0.5, 1.5, 2.5 days → within 3 days (kept); 3.5, 4.5 days → older than 3 days (deleted)
        ages_days = [0.5, 1.5, 2.5, 3.5, 4.5]
        records = [
            make_log_record_row(i + 1, now - (age * SECONDS_PER_DAY), f"age {age} days")
            for i, age in enumerate(ages_days)
        ]
        await db_service_writer._insert_log_records(records)  # pyright: ignore[reportPrivateUsage]

        # log_retention_days=3: records at 0.5, 1.5, 2.5 days old are kept;
        # records at 3.5 and 4.5 days old are deleted
        await retention_service._do_run_retention_cleanup()  # pyright: ignore[reportPrivateUsage]

        cursor = await db.execute("SELECT COUNT(*) FROM log_records")
        count = (await cursor.fetchone())[0]
        assert count == 3  # 0.5, 1.5, 2.5 day records remain

    async def test_retention_uses_log_retention_days_not_db_retention_days(
        self,
        db: aiosqlite.Connection,
        db_service_writer: DatabaseService,
        retention_service: DatabaseService,
    ) -> None:
        """Retention for log_records uses log_retention_days, not db_retention_days."""
        # log_retention_days=3, db_retention_days=7
        # A record 5 days old is within db_retention_days but outside log_retention_days
        now = time.time()
        await db_service_writer._insert_log_records(  # pyright: ignore[reportPrivateUsage]
            [make_log_record_row(1, now - (5 * SECONDS_PER_DAY), "5 days old")],
        )

        await retention_service._do_run_retention_cleanup()  # pyright: ignore[reportPrivateUsage]

        # Should be deleted (5 days > 3 day log_retention_days)
        cursor = await db.execute("SELECT COUNT(*) FROM log_records")
        count = (await cursor.fetchone())[0]
        assert count == 0

    async def test_tier_aware_retention_exact_survival_set(
        self,
        db: aiosqlite.Connection,
        mock_hassette_for_db: MagicMock,
        retention_service: DatabaseService,
    ) -> None:
        """Framework and app tier executions use independent retention cutoffs.

        ``mock_hassette_for_db`` defaults to ``framework_retention_days=1`` and
        ``retention_days=7`` (unmodified ``DatabaseConfig`` defaults). Seed both tiers at the
        same set of ages and assert the exact survival set each cutoff implies.
        """
        now = time.time()
        ages_days = [0.5, 1.5, 2, 5, 8]
        for age in ages_days:
            ts = now - (age * SECONDS_PER_DAY)
            await insert_tiered_execution(db, ts, SOURCE_TIER_FRAMEWORK)
            await insert_tiered_execution(db, ts, SOURCE_TIER_APP)
        await db.commit()

        await retention_service._do_run_retention_cleanup()  # pyright: ignore[reportPrivateUsage]

        cursor = await db.execute("SELECT execution_start_ts FROM executions WHERE source_tier = 'framework'")
        framework_remaining = [row[0] for row in await cursor.fetchall()]
        assert len(framework_remaining) == 1  # only the 0.5-day-old row survives a 1-day cutoff

        cursor = await db.execute("SELECT execution_start_ts FROM executions WHERE source_tier = 'app'")
        app_remaining = [row[0] for row in await cursor.fetchall()]
        assert len(app_remaining) == 4  # 0.5, 1.5, 2, 5-day-old rows survive a 7-day cutoff; 8 is deleted

    async def test_per_target_failure_isolation(
        self,
        db: aiosqlite.Connection,
        caplog: pytest.LogCaptureFixture,
        retention_service: DatabaseService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A DELETE failure on one target does not roll back or block other targets' deletes."""
        now = time.time()
        old_ts = now - (10 * SECONDS_PER_DAY)

        # blocking_events (priority 2) — the target forced to fail below.
        await insert_blocking_event(db, old_ts)
        # app executions (priority 3) — should still be deleted despite the failure above.
        await insert_tiered_execution(db, old_ts, SOURCE_TIER_APP)
        await db.commit()

        monkeypatch.setattr(db, "execute", make_failing_execute(db, "DELETE FROM blocking_events"))

        with caplog.at_level(logging.INFO):
            await retention_service._do_run_retention_cleanup()  # pyright: ignore[reportPrivateUsage]

        # blocking_events row survives — its target's DELETE raised and was rolled back.
        cursor = await db.execute("SELECT COUNT(*) FROM blocking_events")
        assert (await cursor.fetchone())[0] == 1

        # app executions row is still deleted — a later target is unaffected by the earlier failure.
        cursor = await db.execute("SELECT COUNT(*) FROM executions")
        assert (await cursor.fetchone())[0] == 0

        assert "Retention cleanup failed for blocking events" in caplog.text
        assert "blocking events" in caplog.text  # failed_labels surfaced in the summary log

    async def test_parent_guard_skipped_when_target_failed(
        self,
        db: aiosqlite.Connection,
        retention_service: DatabaseService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Parent-guard deletes run only when every _RETENTION_TABLES target succeeded."""
        now = time.time()
        old_retired = now - (10 * SECONDS_PER_DAY)

        async def insert_retired_listener(name: str) -> int:
            cursor = await db.execute(
                "INSERT INTO listeners (app_key, instance_index, name, handler_method, topic, "
                "source_location, retired_at) VALUES ('test_app', 0, ?, 'on_x', 'hass.event', 'test.py:1', ?)",
                (name, old_retired),
            )
            await db.commit()
            assert cursor.lastrowid is not None
            return cursor.lastrowid

        # First run: no target fails, so the parent-guard deletes the retired listener.
        listener1_id = await insert_retired_listener("listener1")
        await retention_service._do_run_retention_cleanup()  # pyright: ignore[reportPrivateUsage]

        cursor = await db.execute("SELECT id FROM listeners WHERE id = ?", (listener1_id,))
        assert await cursor.fetchone() is None

        # Second run: force a target failure, so the parent-guard must be skipped entirely.
        listener2_id = await insert_retired_listener("listener2")

        monkeypatch.setattr(db, "execute", make_failing_execute(db, "DELETE FROM blocking_events"))
        await retention_service._do_run_retention_cleanup()  # pyright: ignore[reportPrivateUsage]

        cursor = await db.execute("SELECT id FROM listeners WHERE id = ?", (listener2_id,))
        assert await cursor.fetchone() is not None  # survives: parent-guard was gated off

    async def test_retention_cleanup_batches_large_deletes(
        self,
        db: aiosqlite.Connection,
        retention_service: DatabaseService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A target with more rows than the batch size deletes across multiple commits."""
        now = time.time()
        old_ts = now - (5 * SECONDS_PER_DAY)  # older than framework_retention_days=1
        row_count = 1200  # > _RETENTION_DELETE_BATCH (1000)
        for _ in range(row_count):
            await insert_tiered_execution(db, old_ts, SOURCE_TIER_FRAMEWORK)
        await db.commit()

        original_execute = db.execute
        delete_batch_calls = 0

        async def counting_execute(sql: str, *args: Any, **kwargs: Any) -> Any:
            nonlocal delete_batch_calls
            if sql.strip().startswith("DELETE FROM executions WHERE id IN"):
                delete_batch_calls += 1
            return await original_execute(sql, *args, **kwargs)

        monkeypatch.setattr(db, "execute", counting_execute)
        await retention_service._do_run_retention_cleanup()  # pyright: ignore[reportPrivateUsage]

        cursor = await db.execute("SELECT COUNT(*) FROM executions")
        assert (await cursor.fetchone())[0] == 0  # all deleted

        # Framework target alone needs 2 batches (1000 + 200); the app-tier target contributes at
        # least 1 more no-op batch, so >= 2 total DELETE calls proves batching actually happened.
        assert delete_batch_calls >= 2

    async def test_retention_cleanup_batch_cap_warns_and_defers_remainder(
        self,
        db: aiosqlite.Connection,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
        retention_service: DatabaseService,
    ) -> None:
        """A target with more matching rows than the batch cap allows stops early, logs a
        WARNING naming the target and the cap, and leaves the remainder for the next hourly
        cycle — so a chronically-behind target is visible rather than indistinguishable from
        one that's merely converging.
        """
        retention_service.hassette.config.database.retention_delete_batch = 2
        retention_service.hassette.config.database.retention_max_batches_per_target = 3

        now = time.time()
        old_ts = now - (5 * SECONDS_PER_DAY)  # older than framework_retention_days=1
        row_count = 10  # > cap (3 batches * 2 rows = 6)
        for _ in range(row_count):
            await insert_tiered_execution(db, old_ts, SOURCE_TIER_FRAMEWORK)
        await db.commit()

        with caplog.at_level(logging.INFO):
            await retention_service._do_run_retention_cleanup()  # pyright: ignore[reportPrivateUsage]

        cursor = await db.execute("SELECT COUNT(*) FROM executions WHERE source_tier = 'framework'")
        assert (await cursor.fetchone())[0] == 4  # 10 - (3 batches * 2 rows) = 4 remain for next cycle

        assert "framework executions hit the 3-batch cap" in caplog.text

    async def test_parent_guard_gated_when_target_batch_capped(
        self,
        db: aiosqlite.Connection,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
        retention_service: DatabaseService,
    ) -> None:
        """A target that hits the batch cap (no exception, just a normal return) must gate
        the parent-guard exactly like an exception-raising failure.

        Regression test for a bug where batch-cap exhaustion returned normally, so
        ``failed_labels`` never got populated and the parent-guard's ``if not failed_labels``
        gate treated a known-incomplete target as fully cleared — risking a real
        ``CHECK ((listener_id IS NOT NULL) + (job_id IS NOT NULL) = 1)`` violation via
        ``ON DELETE SET NULL`` when a retired listener's old (not "recent", so not blocked by
        the guard's own NOT EXISTS check), not-yet-deleted children lose their only surviving
        FK reference.
        """
        retention_service.hassette.config.database.retention_delete_batch = 2
        retention_service.hassette.config.database.retention_max_batches_per_target = 3

        now = time.time()
        old_retired = now - (10 * SECONDS_PER_DAY)  # older than retention_days=7
        old_exec_ts = now - (9 * SECONDS_PER_DAY)  # older than retention_days=7 too — not "recent" to the guard

        cursor = await db.execute(
            "INSERT INTO listeners (app_key, instance_index, name, handler_method, topic, "
            "source_location, retired_at) VALUES ('test_app', 0, 'listener1', 'on_x', 'hass.event', "
            "'test.py:1', ?)",
            (old_retired,),
        )
        await db.commit()
        listener_id = cursor.lastrowid
        assert listener_id is not None

        # Only old (past-cutoff) children — satisfies the parent-guard's own NOT EXISTS check
        # (it only blocks on *recent* children), but the framework target's batch cap (3
        # batches * 2 rows = 6) leaves 4 of these 10 rows undeleted this cycle — exactly the
        # "incomplete" state the parent-guard must not run against.
        for _ in range(10):
            await db.execute(
                "INSERT INTO executions (kind, listener_id, execution_start_ts, source_tier) "
                "VALUES ('handler', ?, ?, 'framework')",
                (listener_id, old_exec_ts),
            )
        await db.commit()

        with caplog.at_level(logging.INFO):
            await retention_service._do_run_retention_cleanup()  # pyright: ignore[reportPrivateUsage]

        # The listener survives: parent-guard was gated off because the framework target hit
        # the batch cap, even though no exception was raised.
        cursor = await db.execute("SELECT id FROM listeners WHERE id = ?", (listener_id,))
        assert await cursor.fetchone() is not None
        assert "incomplete: framework executions" in caplog.text

        # 4 of 10 rows remain past the batch cap, confirming the target was genuinely
        # incomplete rather than a false trigger.
        cursor = await db.execute(
            "SELECT COUNT(*) FROM executions WHERE listener_id = ?",
            (listener_id,),
        )
        assert (await cursor.fetchone())[0] == 4

    async def test_partial_batch_progress_reported_on_later_batch_failure(
        self,
        db: aiosqlite.Connection,
        caplog: pytest.LogCaptureFixture,
        retention_service: DatabaseService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A failure on the 2nd+ batch of a target still reports the 1st batch's real count.

        Regression test: `_delete_target_batched()` accumulates `total_deleted` in a local
        variable that is lost if a later batch's DELETE raises — the caller must recover the
        partial count from the exception, not report a false zero for a target that already
        committed real, durable progress before failing.
        """
        now = time.time()
        old_ts = now - (5 * SECONDS_PER_DAY)  # older than framework_retention_days=1
        row_count = 1200  # > _RETENTION_DELETE_BATCH (1000) — forces 2 batches for this target
        for _ in range(row_count):
            await insert_tiered_execution(db, old_ts, SOURCE_TIER_FRAMEWORK)
        await db.commit()

        original_execute = db.execute
        delete_calls = 0

        async def failing_second_batch_execute(sql: str, *args: Any, **kwargs: Any) -> Any:
            nonlocal delete_calls
            if sql.strip().startswith("DELETE FROM executions WHERE id IN"):
                delete_calls += 1
                if delete_calls == 2:
                    raise sqlite3.OperationalError("simulated failure on 2nd batch")
            return await original_execute(sql, *args, **kwargs)

        monkeypatch.setattr(db, "execute", failing_second_batch_execute)

        with caplog.at_level(logging.INFO):
            await retention_service._do_run_retention_cleanup()  # pyright: ignore[reportPrivateUsage]

        # First batch (1000 rows) committed and is durable; only the 2nd batch's attempt failed.
        cursor = await db.execute("SELECT COUNT(*) FROM executions WHERE source_tier = 'framework'")
        assert (await cursor.fetchone())[0] == 200  # 1200 - 1000 committed by the first batch

        # The summary must report the real partial count (1000), not a false zero.
        assert "1000 framework executions" in caplog.text
        assert "failed: framework executions" in caplog.text

    async def test_retention_batch_cap_exact_multiple_not_marked_incomplete(
        self,
        db: aiosqlite.Connection,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
        retention_service: DatabaseService,
    ) -> None:
        """When matching rows are an exact multiple of the batch cap, the final full batch
        removes the last stale row — the target must not be marked incomplete just because
        every batch happened to run full-sized.

        Regression test: the batched-delete ``for``/``else`` previously declared
        ``exhausted = True`` whenever the loop ran out of iterations without an early
        ``break``, even when the final full batch deleted the very last matching row. That
        falsely skipped parent-guard cleanup and warned about a backlog that no longer exists.
        """
        retention_service.hassette.config.database.retention_delete_batch = 2
        retention_service.hassette.config.database.retention_max_batches_per_target = 3

        now = time.time()
        old_ts = now - (5 * SECONDS_PER_DAY)  # older than framework_retention_days=1
        row_count = 6  # exactly 3 batches * 2 rows — the last batch removes the last stale row
        for _ in range(row_count):
            await insert_tiered_execution(db, old_ts, SOURCE_TIER_FRAMEWORK)
        await db.commit()

        with caplog.at_level(logging.INFO):
            await retention_service._do_run_retention_cleanup()  # pyright: ignore[reportPrivateUsage]

        cursor = await db.execute("SELECT COUNT(*) FROM executions WHERE source_tier = 'framework'")
        assert (await cursor.fetchone())[0] == 0  # all 6 rows deleted, nothing left over

        assert "hit the 3-batch cap" not in caplog.text
        assert "incomplete: framework executions" not in caplog.text

    async def test_stale_row_probe_failure_isolated_to_target(
        self,
        db: aiosqlite.Connection,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
        retention_service: DatabaseService,
    ) -> None:
        """A transient error from the stale-row probe (reached only when every batch for a
        target ran full-sized) is caught and surfaces as a per-target failure — not an
        uncaught exception that aborts the whole cleanup and skips every other target.

        Regression test: the probe's ``execute()``/``fetchone()`` calls previously sat outside
        the target's ``try/except _RetentionBatchError`` isolation, so a transient SQLite error
        there propagated straight out of ``_delete_target_batched()`` uncaught by
        ``_do_run_retention_cleanup()``'s ``except _RetentionBatchError`` handler, aborting the
        entire cleanup run.
        """
        retention_service.hassette.config.database.retention_delete_batch = 2
        retention_service.hassette.config.database.retention_max_batches_per_target = 3

        now = time.time()
        old_framework_ts = now - (5 * SECONDS_PER_DAY)  # older than framework_retention_days=1
        row_count = 6  # exactly 3 batches * 2 rows — every batch runs full-sized, reaching the probe
        for _ in range(row_count):
            await insert_tiered_execution(db, old_framework_ts, SOURCE_TIER_FRAMEWORK)
        # A second target's old row, to prove it still gets processed despite the framework
        # target's probe failure.
        old_app_ts = now - (10 * SECONDS_PER_DAY)  # older than retention_days=7
        await insert_tiered_execution(db, old_app_ts, SOURCE_TIER_APP)
        await db.commit()

        # Fail only the stale-row probe's SELECT ("SELECT 1 FROM executions WHERE ..."), not the
        # batched DELETE's inner subselect ("... SELECT id FROM executions WHERE ...").
        monkeypatch.setattr(db, "execute", make_failing_execute(db, "SELECT 1 FROM executions"))

        with caplog.at_level(logging.INFO):
            await retention_service._do_run_retention_cleanup()  # pyright: ignore[reportPrivateUsage]

        # All 3 batches for the framework target committed before the probe raised — that
        # progress is real and durable despite the probe failure.
        cursor = await db.execute("SELECT COUNT(*) FROM executions WHERE source_tier = 'framework'")
        assert (await cursor.fetchone())[0] == 0

        # The app-tier target was not aborted by the framework target's probe failure.
        cursor = await db.execute("SELECT COUNT(*) FROM executions WHERE source_tier = 'app'")
        assert (await cursor.fetchone())[0] == 0

        assert "Retention cleanup failed for framework executions" in caplog.text
        assert "failed: framework executions" in caplog.text

    async def test_per_target_duration_logging(
        self,
        db: aiosqlite.Connection,
        caplog: pytest.LogCaptureFixture,
        retention_service: DatabaseService,
    ) -> None:
        """Retention cleanup logs a per-target line naming the tier label and elapsed duration."""
        now = time.time()
        old_ts = now - (10 * SECONDS_PER_DAY)
        await insert_tiered_execution(db, old_ts, SOURCE_TIER_FRAMEWORK)
        await insert_tiered_execution(db, old_ts, SOURCE_TIER_APP)
        await db.commit()

        with caplog.at_level(logging.INFO):
            await retention_service._do_run_retention_cleanup()  # pyright: ignore[reportPrivateUsage]

        assert "framework executions in" in caplog.text
        assert "app executions in" in caplog.text


class TestSizeFailsafe:
    """Priority ordering per ``_RETENTION_TABLES``'s restructure: framework executions (1) <
    blocking events (2) < app executions (3) < log records (4). Execution records are now the
    highest-priority (deleted-first) group, not log records — see design/specs/110-retention-overhaul.
    The DELETE queries filter by ``source_tier`` inside the inner SELECT (when a target declares
    one), so each tier's own oldest-N rows are targeted rather than the globally-oldest N rows
    filtered down afterward.
    """

    async def seed_both_tables(
        self, db: aiosqlite.Connection, db_service_writer: DatabaseService, log_count: int = 10, exec_count: int = 5
    ) -> None:
        """Seed log_records and executions."""
        now = time.time()
        logs = [make_log_record_row(i, now - (i * 10), f"log {i}") for i in range(1, log_count + 1)]
        await db_service_writer._insert_log_records(logs)  # pyright: ignore[reportPrivateUsage]

        for i in range(exec_count):
            await db.execute(
                "INSERT INTO executions (kind, listener_id, execution_start_ts) VALUES ('handler', 1, ?)",
                (now - i * 10,),
            )
        await db.commit()

    async def test_size_failsafe_deletes_execution_records_before_log_records(
        self,
        db: aiosqlite.Connection,
        db_service_writer: DatabaseService,
        mock_hassette_for_db: MagicMock,
        retention_service: DatabaseService,
    ) -> None:
        """Size failsafe deletes from executions (priority 1/3) before log_records (priority 4).

        ``seed_both_tables`` inserts executions without an explicit ``source_tier``, so they
        fall in the default 'app' tier (priority 3) — the framework tier (priority 1) and
        blocking_events (priority 2) are empty and each consume one end-of-priority size check
        before priority 3 is even reached: entry check (1) + priority-1-empty (2) +
        priority-2-empty (3) precede the priority-3 batch that actually deletes rows.
        """
        await self.seed_both_tables(db, db_service_writer, log_count=10, exec_count=5)

        mock_hassette_for_db.config.database.max_size_mb = 0.0001  # tiny limit

        calls = 0

        def mock_size() -> float:
            nonlocal calls
            calls += 1
            if calls <= 3:
                return 10.0
            return 0.0

        retention_service.get_db_size_mb = mock_size  # pyright: ignore[reportAttributeAccessIssue]
        await retention_service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]

        # log_records should NOT be touched (executions were sufficient)
        cursor = await db.execute("SELECT COUNT(*) FROM log_records")
        log_count = (await cursor.fetchone())[0]
        assert log_count == 10  # untouched

        cursor = await db.execute("SELECT COUNT(*) FROM executions")
        exec_count = (await cursor.fetchone())[0]
        assert exec_count < 5  # some deleted

    async def test_size_failsafe_proceeds_to_log_records_if_execution_deletion_insufficient(
        self,
        db: aiosqlite.Connection,
        db_service_writer: DatabaseService,
        mock_hassette_for_db: MagicMock,
        retention_service: DatabaseService,
    ) -> None:
        """If deleting executions can't bring size under limit, log_records are also deleted.

        Mock sizing: draining executions (priorities 1 and 3) exhausts the table but the DB
        remains over limit, so the failsafe proceeds to delete log_records (priority 4).
        """
        # Seed a small number of executions (all get deleted but still over limit)
        await self.seed_both_tables(db, db_service_writer, log_count=5, exec_count=2)

        mock_hassette_for_db.config.database.max_size_mb = 0.0001

        calls = 0

        def mock_size() -> float:
            nonlocal calls
            calls += 1
            if calls <= 5:
                return 10.0
            return 0.0

        retention_service.get_db_size_mb = mock_size  # pyright: ignore[reportAttributeAccessIssue]
        await retention_service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]

        # log_records should have been deleted (execution deletion was insufficient)
        cursor = await db.execute("SELECT COUNT(*) FROM log_records")
        log_remaining = (await cursor.fetchone())[0]
        assert log_remaining < 5  # some deleted

    async def test_size_failsafe_scopes_delete_to_own_tier_not_globally_oldest(
        self,
        db: aiosqlite.Connection,
        mock_hassette_for_db: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        retention_service: DatabaseService,
    ) -> None:
        """The tier filter must live inside the inner SELECT, not the outer DELETE.

        Seeds 5 framework-tier executions and 1 app-tier execution whose timestamp is far
        older than any framework row — the app row is the globally-oldest row overall. With
        the batch size forced below the framework tier's row count, a single batch must
        delete exactly the oldest N *framework* rows and leave the app row untouched. If the
        tier filter were applied on the outer DELETE instead of the inner SELECT, the inner
        SELECT would rank the app row among the batch's oldest IDs, the outer filter would
        discard it, and fewer than N framework rows would be deleted in the batch.
        """
        retention_service.hassette.config.database.size_failsafe_delete_batch = 3

        now = time.time()
        # Framework tier: ages 10, 20, 30, 40, 50 seconds ago (50 is the tier's oldest).
        framework_ages = [10, 20, 30, 40, 50]
        for age in framework_ages:
            await insert_tiered_execution(db, now - age, SOURCE_TIER_FRAMEWORK)
        # App tier: a single row far older than every framework row — globally oldest overall.
        await insert_tiered_execution(db, now - 100_000, SOURCE_TIER_APP)
        # Untouched control rows in the lower-priority groups.
        await insert_blocking_event(db, now - 1)
        await db.commit()

        mock_hassette_for_db.config.database.max_size_mb = 0.0001

        calls = 0

        def mock_size() -> float:
            nonlocal calls
            calls += 1
            # Over limit for the entry check; under limit immediately after the first batch —
            # confines the whole run to a single priority-1 batch.
            return 10.0 if calls == 1 else 0.0

        retention_service.get_db_size_mb = mock_size  # pyright: ignore[reportAttributeAccessIssue]
        await retention_service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]

        cursor = await db.execute(
            "SELECT execution_start_ts FROM executions WHERE source_tier = 'framework' ORDER BY execution_start_ts"
        )
        remaining_framework = [row[0] for row in await cursor.fetchall()]
        # The batch (LIMIT 3) deletes the 3 oldest framework rows (ages 50, 40, 30); the 2
        # newest (ages 20, 10) survive.
        assert len(remaining_framework) == 2
        assert sorted(now - ts for ts in remaining_framework) == sorted([10, 20])

        # The app-tier row (globally oldest) must survive — it is not part of the framework tier.
        cursor = await db.execute("SELECT COUNT(*) FROM executions WHERE source_tier = 'app'")
        assert (await cursor.fetchone())[0] == 1

        # Lower-priority groups (blocking_events, log_records) are never reached.
        cursor = await db.execute("SELECT COUNT(*) FROM blocking_events")
        assert (await cursor.fetchone())[0] == 1

    async def test_size_failsafe_full_priority_chain_order(
        self,
        db: aiosqlite.Connection,
        db_service_writer: DatabaseService,
        mock_hassette_for_db: MagicMock,
        retention_service: DatabaseService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When the DB stays over limit through every tier, deletion proceeds framework
        executions -> blocking events -> app executions -> log records, in that order.
        """
        now = time.time()
        await insert_tiered_execution(db, now - 10, SOURCE_TIER_FRAMEWORK)
        await insert_blocking_event(db, now - 10)
        await insert_tiered_execution(db, now - 10, SOURCE_TIER_APP)
        await db.commit()
        await db_service_writer._insert_log_records(  # pyright: ignore[reportPrivateUsage]
            [make_log_record_row(1, now - 10, "log")]
        )

        mock_hassette_for_db.config.database.max_size_mb = 0.0001

        original_execute = db.execute
        delete_order: list[str] = []

        async def tracking_execute(sql: str, *args: Any, **kwargs: Any) -> Any:
            stripped = sql.strip()
            if stripped.startswith("DELETE FROM executions") and args and args[0] and SOURCE_TIER_FRAMEWORK in args[0]:
                delete_order.append("framework executions")
            elif stripped.startswith("DELETE FROM executions") and args and args[0] and SOURCE_TIER_APP in args[0]:
                delete_order.append("app executions")
            elif stripped.startswith("DELETE FROM blocking_events"):
                delete_order.append("blocking events")
            elif stripped.startswith("DELETE FROM log_records"):
                delete_order.append("log records")
            return await original_execute(sql, *args, **kwargs)

        monkeypatch.setattr(db, "execute", tracking_execute)

        # Always report over limit so the failsafe drains every group.
        retention_service.get_db_size_mb = lambda: 10.0  # pyright: ignore[reportAttributeAccessIssue]
        await retention_service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]

        # Each group's inner loop runs one extra (no-op) iteration after draining its rows, so
        # dedupe consecutive repeats while preserving first-seen order.
        unique_order = list(dict.fromkeys(delete_order))
        assert unique_order == ["framework executions", "blocking events", "app executions", "log records"]

    async def test_size_failsafe_blocking_events_deleted_at_priority_two(
        self,
        db: aiosqlite.Connection,
        mock_hassette_for_db: MagicMock,
        retention_service: DatabaseService,
    ) -> None:
        """blocking_events (priority 2) drains after framework executions (1) and before
        app executions (3) / log_records (4).
        """
        now = time.time()
        for i in range(3):
            await insert_blocking_event(db, now - i)
        await insert_tiered_execution(db, now - 10, SOURCE_TIER_APP)
        await db.commit()

        mock_hassette_for_db.config.database.max_size_mb = 0.0001

        calls = 0

        def mock_size() -> float:
            nonlocal calls
            calls += 1
            # Over limit through the framework-tier pass (no rows there); under limit once
            # blocking_events has been drained.
            return 10.0 if calls <= 2 else 0.0

        retention_service.get_db_size_mb = mock_size  # pyright: ignore[reportAttributeAccessIssue]
        await retention_service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]

        cursor = await db.execute("SELECT COUNT(*) FROM blocking_events")
        assert (await cursor.fetchone())[0] == 0  # drained at priority 2

        cursor = await db.execute("SELECT COUNT(*) FROM executions WHERE source_tier = 'app'")
        assert (await cursor.fetchone())[0] == 1  # priority 3 never reached

    async def test_size_failsafe_logs_exhaustion_warning_with_consecutive_count(
        self,
        db: aiosqlite.Connection,
        db_service_writer: DatabaseService,
        mock_hassette_for_db: MagicMock,
        caplog: pytest.LogCaptureFixture,
        retention_service: DatabaseService,
    ) -> None:
        """A run that drains every tier and remains over the size limit logs a WARNING naming
        the consecutive exhaustion count.
        """
        now = time.time()
        await insert_tiered_execution(db, now - 10, SOURCE_TIER_FRAMEWORK)
        await insert_blocking_event(db, now - 10)
        await insert_tiered_execution(db, now - 10, SOURCE_TIER_APP)
        await db.commit()
        await db_service_writer._insert_log_records(  # pyright: ignore[reportPrivateUsage]
            [make_log_record_row(1, now - 10, "log")]
        )

        mock_hassette_for_db.config.database.max_size_mb = 0.0001
        # Always report over limit — every tier drains and the DB is still "too big".
        retention_service.get_db_size_mb = lambda: 10.0  # pyright: ignore[reportAttributeAccessIssue]

        with caplog.at_level(logging.WARNING):
            await retention_service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]

        assert retention_service._consecutive_exhaustion_triggers == 1  # pyright: ignore[reportPrivateUsage]
        assert "exhausted" in caplog.text
        assert "1 consecutive" in caplog.text

        caplog.clear()
        # Re-seed (previous run deleted everything) and run again — count must increment.
        await insert_tiered_execution(db, now - 10, SOURCE_TIER_FRAMEWORK)
        await db.commit()

        with caplog.at_level(logging.WARNING):
            await retention_service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]

        assert retention_service._consecutive_exhaustion_triggers == 2  # pyright: ignore[reportPrivateUsage]
        assert "2 consecutive" in caplog.text

    async def test_size_failsafe_stops_when_higher_priority_tier_hits_iteration_cap(
        self,
        db: aiosqlite.Connection,
        db_service_writer: DatabaseService,
        mock_hassette_for_db: MagicMock,
        caplog: pytest.LogCaptureFixture,
        retention_service: DatabaseService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When the highest-priority tier (framework executions) hits its per-cycle iteration
        cap while the database is still over the limit, the run must stop there rather than
        advancing to lower-priority tiers — deleting app/log data while the higher-priority
        tier's own backlog remains would defeat the priority ordering the tiers exist for.
        """
        retention_service.hassette.config.database.size_failsafe_max_iterations = 2
        retention_service.hassette.config.database.size_failsafe_delete_batch = 2

        now = time.time()
        # Framework tier: far more rows than the 2-iteration * 2-row cap (4) can ever drain.
        for i in range(20):
            await insert_tiered_execution(db, now - i, SOURCE_TIER_FRAMEWORK)
        await db.commit()
        await db_service_writer._insert_log_records(  # pyright: ignore[reportPrivateUsage]
            [make_log_record_row(1, now - 1, "log")]
        )

        mock_hassette_for_db.config.database.max_size_mb = 0.0001
        # Never report under the limit — forces the framework tier to keep going until it hits
        # the iteration cap instead of naturally draining and breaking out early.
        retention_service.get_db_size_mb = lambda: 10.0  # pyright: ignore[reportAttributeAccessIssue]

        with caplog.at_level(logging.INFO):
            await retention_service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]

        # Only the capped iterations' worth was deleted (2 iterations * 2 rows = 4); the tier's
        # own large remaining backlog proves the run stopped rather than exhausting the tier.
        cursor = await db.execute("SELECT COUNT(*) FROM executions WHERE source_tier = 'framework'")
        assert (await cursor.fetchone())[0] == 16

        # Lower-priority tier (log_records) was never touched.
        cursor = await db.execute("SELECT COUNT(*) FROM log_records")
        assert (await cursor.fetchone())[0] == 1

        assert "capped at 2 iterations" in caplog.text
        assert "stopped early" in caplog.text
        assert "framework executions" in caplog.text

    async def test_size_failsafe_exact_boundary_drain_proceeds_to_next_tier(
        self,
        db: aiosqlite.Connection,
        mock_hassette_for_db: MagicMock,
        caplog: pytest.LogCaptureFixture,
        retention_service: DatabaseService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When a tier's row count is an exact multiple of the iteration cap * batch size, the
        final full batch drains the tier's own rows even though every iteration ran full-sized.
        The run must not treat this as capped just because the database is still over the
        limit — the remaining overage is attributable to a lower-priority tier, and the run
        must proceed to (and delete from) that tier instead of stopping early.

        Regression test: the size failsafe previously declared a tier capped whenever its
        iteration loop ran to the cap while the database stayed oversized, without checking
        whether the tier's own rows were actually exhausted.
        """
        retention_service.hassette.config.database.size_failsafe_max_iterations = 2
        retention_service.hassette.config.database.size_failsafe_delete_batch = 2

        now = time.time()
        # Framework tier: exactly 2 iterations * 2 rows = 4 rows — the final full batch drains
        # the tier's own last row.
        for i in range(4):
            await insert_tiered_execution(db, now - i, SOURCE_TIER_FRAMEWORK)
        # Blocking events (priority 2): the sole reason the DB stays over limit after the
        # framework tier drains.
        await insert_blocking_event(db, now - 1)
        await db.commit()

        mock_hassette_for_db.config.database.max_size_mb = 0.0001

        calls = 0

        def mock_size() -> float:
            nonlocal calls
            calls += 1
            # Over limit for: entry check, both framework iterations, and the post-tier check —
            # under limit only once blocking_events (the last remaining data) is deleted too.
            return 10.0 if calls <= 4 else 0.0

        retention_service.get_db_size_mb = mock_size  # pyright: ignore[reportAttributeAccessIssue]

        with caplog.at_level(logging.INFO):
            await retention_service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]

        # Framework tier fully drained by the exact-boundary final batch.
        cursor = await db.execute("SELECT COUNT(*) FROM executions WHERE source_tier = 'framework'")
        assert (await cursor.fetchone())[0] == 0

        # The run proceeded to blocking_events instead of stopping at the "capped" framework
        # tier — proving the stale-row probe correctly found no remaining framework rows.
        cursor = await db.execute("SELECT COUNT(*) FROM blocking_events")
        assert (await cursor.fetchone())[0] == 0

        assert "capped" not in caplog.text
        assert "stopped early" not in caplog.text

    async def test_size_failsafe_stale_row_probe_failure_isolated(
        self,
        db: aiosqlite.Connection,
        db_service_writer: DatabaseService,
        mock_hassette_for_db: MagicMock,
        caplog: pytest.LogCaptureFixture,
        retention_service: DatabaseService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A transient error from the size-failsafe's own stale-row probe (the twin of
        ``_delete_target_batched()``'s probe, reached only when a tier's iteration loop runs to
        completion without naturally draining) is caught and isolated to that tier — not an
        uncaught exception that aborts the whole failsafe cycle and skips lower-priority tiers.

        Regression test: this probe was added alongside the retention-path probe's isolation
        fix (see ``test_stale_row_probe_failure_isolated_to_target``) but was itself initially
        left unguarded, reproducing the exact bug class this PR exists to fix.
        """
        retention_service.hassette.config.database.size_failsafe_max_iterations = 2
        retention_service.hassette.config.database.size_failsafe_delete_batch = 2

        now = time.time()
        # Framework tier: far more rows than the 2-iteration * 2-row cap (4) can ever drain —
        # every iteration deletes a full batch, so the loop runs to completion and reaches the
        # probe instead of breaking early via group_deleted == 0.
        for i in range(20):
            await insert_tiered_execution(db, now - i, SOURCE_TIER_FRAMEWORK)
        await db.commit()
        await db_service_writer._insert_log_records(  # pyright: ignore[reportPrivateUsage]
            [make_log_record_row(1, now - 1, "log")]
        )

        mock_hassette_for_db.config.database.max_size_mb = 0.0001
        # Never report under the limit — forces the framework tier's loop to run to completion.
        retention_service.get_db_size_mb = lambda: 10.0  # pyright: ignore[reportAttributeAccessIssue]

        # Fail only the stale-row probe's SELECT, not the batched DELETE's inner subselect.
        monkeypatch.setattr(db, "execute", make_failing_execute(db, "SELECT 1 FROM executions"))

        with caplog.at_level(logging.INFO):
            await retention_service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]

        # The framework tier's probe failed and was skipped rather than the whole run aborting —
        # the lower-priority log_records tier still ran.
        cursor = await db.execute("SELECT COUNT(*) FROM log_records")
        assert (await cursor.fetchone())[0] == 0

        assert "Size failsafe stale-row probe failed for framework executions" in caplog.text
        # A probe failure is not a genuine full-tier drain — must not count as exhaustion.
        assert retention_service._consecutive_exhaustion_triggers == 0  # pyright: ignore[reportPrivateUsage]

    async def test_size_failsafe_capped_cycle_resets_exhaustion_streak(
        self,
        db: aiosqlite.Connection,
        db_service_writer: DatabaseService,
        mock_hassette_for_db: MagicMock,
        retention_service: DatabaseService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A capped-but-not-exhausted cycle must reset ``_consecutive_exhaustion_triggers`` to 0,
        not merely leave it unchanged — otherwise a later genuinely-exhausted cycle reports a
        streak count that silently spans the interruption.

        Regression test: run 1 fully exhausts every tier (counter -> 1). Run 2's framework tier
        hits its iteration cap and stops the cycle early (not a genuine drain) — the counter must
        drop to 0, not stay at 1. Run 3 fully exhausts again — the counter must read 1 (a fresh
        streak), not 2 (as if run 2's interruption never happened).
        """
        retention_service.hassette.config.database.size_failsafe_max_iterations = 2
        retention_service.hassette.config.database.size_failsafe_delete_batch = 2

        mock_hassette_for_db.config.database.max_size_mb = 0.0001

        now = time.time()
        # Always report over limit — every run below stays "oversized" per the mocked size, so
        # every over-limit branch (exhaustion, capped) is exercised deliberately by row counts
        # rather than by the mocked size flipping under the limit.
        retention_service.get_db_size_mb = lambda: 10.0  # pyright: ignore[reportAttributeAccessIssue]

        # Run 1: a single framework row and a single log record — small enough that both tiers
        # naturally drain within the 2-iteration cap. Every tier drains, DB still over limit ->
        # genuine exhaustion.
        await insert_tiered_execution(db, now - 1, SOURCE_TIER_FRAMEWORK)
        await db.commit()
        await db_service_writer._insert_log_records(  # pyright: ignore[reportPrivateUsage]
            [make_log_record_row(1, now - 1, "log")]
        )

        await retention_service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]
        assert retention_service._consecutive_exhaustion_triggers == 1  # pyright: ignore[reportPrivateUsage]

        # Run 2: a framework backlog far larger than the 2-iteration * 2-row cap (4) can ever
        # drain — the tier hits its iteration cap, the stale-row probe finds rows remain, and the
        # cycle stops early instead of advancing. This is the capped path, not a genuine drain.
        for i in range(20):
            await insert_tiered_execution(db, now - i, SOURCE_TIER_FRAMEWORK)
        await db.commit()

        await retention_service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]
        assert retention_service._consecutive_exhaustion_triggers == 0  # pyright: ignore[reportPrivateUsage]

        # Run 3: clear the leftover framework backlog (simulating it having been resolved by an
        # intervening cycle) and seed a small amount of fresh data that again drains every tier
        # naturally within the cap — a genuine exhaustion, starting a fresh streak.
        await db.execute("DELETE FROM executions WHERE source_tier = 'framework'")
        await db.commit()
        await insert_tiered_execution(db, now - 1, SOURCE_TIER_FRAMEWORK)
        await db.commit()
        await db_service_writer._insert_log_records(  # pyright: ignore[reportPrivateUsage]
            [make_log_record_row(2, now - 1, "log")]
        )

        await retention_service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]
        assert retention_service._consecutive_exhaustion_triggers == 1  # pyright: ignore[reportPrivateUsage]

    async def test_size_failsafe_failure_isolation(
        self,
        db: aiosqlite.Connection,
        mock_hassette_for_db: MagicMock,
        caplog: pytest.LogCaptureFixture,
        retention_service: DatabaseService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A DELETE failure on one priority tier is logged with its label, current size, and
        limit, and does not abort lower-priority tiers — the size-failsafe analog of
        ``TestRetentionCleanup.test_per_target_failure_isolation``.
        """
        now = time.time()
        await insert_tiered_execution(db, now - 10, SOURCE_TIER_FRAMEWORK)
        await insert_blocking_event(db, now - 10)
        await insert_tiered_execution(db, now - 10, SOURCE_TIER_APP)
        await db.commit()

        mock_hassette_for_db.config.database.max_size_mb = 0.0001
        # Always report over limit so the failsafe drives through every priority tier.
        retention_service.get_db_size_mb = lambda: 10.0  # pyright: ignore[reportAttributeAccessIssue]

        original_execute = db.execute

        async def failing_framework_execute(sql: str, *args: Any, **kwargs: Any) -> Any:
            if (
                sql.strip().startswith("DELETE FROM executions")
                and args
                and args[0]
                and SOURCE_TIER_FRAMEWORK in args[0]
            ):
                raise sqlite3.OperationalError("simulated failure")
            return await original_execute(sql, *args, **kwargs)

        monkeypatch.setattr(db, "execute", failing_framework_execute)

        with caplog.at_level(logging.INFO):
            await retention_service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]

        # Framework executions tier failed and is left untouched.
        cursor = await db.execute("SELECT COUNT(*) FROM executions WHERE source_tier = 'framework'")
        assert (await cursor.fetchone())[0] == 1

        # Lower-priority tiers still ran despite the framework-tier failure.
        cursor = await db.execute("SELECT COUNT(*) FROM blocking_events")
        assert (await cursor.fetchone())[0] == 0
        cursor = await db.execute("SELECT COUNT(*) FROM executions WHERE source_tier = 'app'")
        assert (await cursor.fetchone())[0] == 0

        assert "Size failsafe failed for framework executions" in caplog.text
        assert "10.0 MB" in caplog.text  # current size
        assert "0.0 MB limit" in caplog.text  # max_size_mb=0.0001 formatted to 1 decimal

        # A tier failing and being skipped is not a genuine full-drain exhaustion — counting it
        # would misattribute the overage to unmanaged data rather than the failed cleanup that
        # actually caused it.
        assert retention_service._consecutive_exhaustion_triggers == 0  # pyright: ignore[reportPrivateUsage]
        assert "failed and were skipped this cycle" in caplog.text


class TestRuntimeQueryServiceWiring:
    async def test_constructor_injection_stores_db_service_and_loop(self) -> None:
        """LogPersistenceHandler stores db_service and loop at construction."""
        mock_db_service = MagicMock()
        loop = asyncio.get_running_loop()
        handler = LogPersistenceHandler(mock_db_service, loop, persistence_level=logging.INFO)
        assert handler._db_service is mock_db_service  # pyright: ignore[reportPrivateUsage]
        assert handler._loop is loop  # pyright: ignore[reportPrivateUsage]

    async def test_persistence_handler_db_write_queue_drops_starts_at_zero(self) -> None:
        """LogPersistenceHandler.db_write_queue_drops starts at 0 after construction."""
        mock_db_service = MagicMock()
        loop = asyncio.get_running_loop()
        handler = LogPersistenceHandler(mock_db_service, loop, persistence_level=20)
        assert handler.db_write_queue_drops == 0

    async def test_persistence_handler_enqueues_records_on_flush(self) -> None:
        """Records are enqueued to db_service when flushed."""
        mock_db_service = MagicMock()
        mock_db_service.enqueue = MagicMock(return_value=True)
        mock_db_service._insert_log_records = MagicMock(return_value=MagicMock())
        loop = asyncio.get_running_loop()
        handler = LogPersistenceHandler(mock_db_service, loop, persistence_level=logging.INFO)

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=1,
            msg="test message",
            args=(),
            exc_info=None,
        )
        # Stamp required attributes
        record.seq = 1  # pyright: ignore[reportAttributeAccessIssue]
        record.app_key = None  # pyright: ignore[reportAttributeAccessIssue]
        record.instance_name = None  # pyright: ignore[reportAttributeAccessIssue]
        record.instance_index = None  # pyright: ignore[reportAttributeAccessIssue]
        record.execution_id = None  # pyright: ignore[reportAttributeAccessIssue]
        record.source_tier = None  # pyright: ignore[reportAttributeAccessIssue]

        handler.emit(record)
        handler.flush_if_pending()

        # _flush schedules via call_soon_threadsafe; yield to the loop to process it
        await asyncio.sleep(0)
        assert mock_db_service.enqueue.called

    async def test_persistence_handler_filters_below_persistence_level(self) -> None:
        """Records below persistence_level are not accumulated."""
        mock_db_service = MagicMock()
        loop = asyncio.get_running_loop()
        handler = LogPersistenceHandler(mock_db_service, loop, persistence_level=logging.INFO)
        debug_record = logging.LogRecord(
            name="test",
            level=logging.DEBUG,
            pathname="",
            lineno=1,
            msg="debug msg",
            args=(),
            exc_info=None,
        )
        handler.emit(debug_record)
        handler.flush_if_pending()

        # No enqueue because it was filtered before accumulation
        assert handler.db_write_queue_drops == 0
        assert handler._batch == []  # pyright: ignore[reportPrivateUsage]
