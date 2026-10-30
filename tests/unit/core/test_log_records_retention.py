"""Unit tests for log_records retention and LogPersistenceHandler wiring."""

import asyncio
import logging
import sqlite3
import time
from typing import Any
from unittest.mock import MagicMock

import aiosqlite
import pytest

from hassette.const.misc import SECONDS_PER_DAY
from hassette.core.database_service import DatabaseService
from hassette.logging_ import LogPersistenceHandler
from tests.support.factories import make_log_record

from ._fixtures_retention import (
    SOURCE_TIER_APP,
    SOURCE_TIER_FRAMEWORK,
    count_rows,
    db,
    db_service_writer,
    insert_blocking_event,
    insert_tiered_execution,
    make_failing_execute,
    make_log_record_row,
    mock_hassette_for_db,
    retention_service,
)

__all__ = ["db", "db_service_writer", "mock_hassette_for_db", "retention_service"]  # re-exposed as fixtures


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

        assert await count_rows(db, "log_records") == 3  # 0.5, 1.5, 2.5 day records remain

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
        assert await count_rows(db, "log_records") == 0

    async def test_tier_aware_retention_exact_survival_set(
        self,
        db: aiosqlite.Connection,
        mock_hassette_for_db: MagicMock,
        retention_service: DatabaseService,
    ) -> None:
        """Framework and app tier executions use independent retention cutoffs.

        ``mock_hassette_for_db`` pins ``framework_retention_days=1`` and
        ``retention_days=7``. Seed both tiers at the
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
        assert await count_rows(db, "blocking_events") == 1

        # app executions row is still deleted — a later target is unaffected by the earlier failure.
        assert await count_rows(db, "executions") == 0

        assert "Retention cleanup failed for blocking events" in caplog.text
        assert "blocking events" in caplog.text  # failed_labels surfaced in the summary log

    async def test_parent_guard_skipped_when_target_failed(
        self,
        db: aiosqlite.Connection,
        retention_service: DatabaseService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Parent-guard deletes run only when every _RETENTION_TABLES target succeeded; a run resets the skip streak."""
        old_retired = time.time() - (10 * SECONDS_PER_DAY)

        async def insert_retired_listener(name: str) -> int:
            cursor = await db.execute(
                "INSERT INTO listeners (app_key, instance_index, name, handler_method, topic, "
                "source_location, retired_at) VALUES ('test_app', 0, ?, 'on_x', 'hass.event', 'test.py:1', ?)",
                (name, old_retired),
            )
            await db.commit()
            assert cursor.lastrowid is not None
            return cursor.lastrowid

        # First run: no target fails, so the parent-guard deletes the retired listener and resets any prior skip streak.
        listener1_id = await insert_retired_listener("listener1")
        retention_service._consecutive_parent_guard_skips = 2  # pyright: ignore[reportPrivateUsage]
        await retention_service._do_run_retention_cleanup()  # pyright: ignore[reportPrivateUsage]
        cursor = await db.execute("SELECT id FROM listeners WHERE id = ?", (listener1_id,))
        assert await cursor.fetchone() is None
        assert retention_service._consecutive_parent_guard_skips == 0  # pyright: ignore[reportPrivateUsage]

        # Next two runs: force a target failure, so the parent-guard is skipped and the skip streak grows.
        listener2_id = await insert_retired_listener("listener2")
        monkeypatch.setattr(db, "execute", make_failing_execute(db, "DELETE FROM blocking_events"))
        for _ in range(2):
            await retention_service._do_run_retention_cleanup()  # pyright: ignore[reportPrivateUsage]
        cursor = await db.execute("SELECT id FROM listeners WHERE id = ?", (listener2_id,))
        assert await cursor.fetchone() is not None  # survives: parent-guard was gated off
        assert retention_service._consecutive_parent_guard_skips == 2  # pyright: ignore[reportPrivateUsage]

    async def test_parent_guard_failure_appears_in_cleanup_summary(
        self,
        db: aiosqlite.Connection,
        caplog: pytest.LogCaptureFixture,
        retention_service: DatabaseService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A parent-guard delete failure (distinct from an upstream target failure) is rolled
        back, logged individually, and also folded into the aggregate "Retention cleanup
        summary" line — not left visible only in its own separate log line.

        Regression test: every _RETENTION_TABLES target succeeds this cycle (no rows to touch),
        so the parent-guard actually runs; only its own DELETE is made to fail.
        """
        monkeypatch.setattr(db, "execute", make_failing_execute(db, "DELETE FROM listeners"))

        with caplog.at_level(logging.INFO):
            await retention_service._do_run_retention_cleanup()  # pyright: ignore[reportPrivateUsage]

        assert "Retention cleanup failed for parent-guard deletes" in caplog.text
        assert "Retention cleanup summary" in caplog.text
        assert "parent-guard deletes failed" in caplog.text

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

        assert await count_rows(db, "executions") == 0  # all deleted

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

        assert (
            await count_rows(db, "executions", source_tier="framework") == 4
        )  # 10 - (3 batches * 2 rows) = 4 remain for next cycle

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
        assert await count_rows(db, "executions", listener_id=listener_id) == 4

    async def test_partial_batch_progress_reported_on_later_batch_failure(
        self,
        db: aiosqlite.Connection,
        caplog: pytest.LogCaptureFixture,
        retention_service: DatabaseService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A failure on the 2nd+ batch of a target still reports the 1st batch's real count.

        Regression test: `_delete_target_batched()` accumulates `total_deleted` in a local
        variable — a later batch's DELETE failing must still hand that count back to the caller,
        not report a false zero for a target that already committed real, durable progress
        before failing.
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
        assert (
            await count_rows(db, "executions", source_tier="framework") == 200
        )  # 1200 - 1000 committed by the first batch

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

        assert await count_rows(db, "executions", source_tier="framework") == 0  # all 6 rows deleted, nothing left over

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
        the target's per-batch error isolation, so a transient SQLite error there propagated
        straight out of ``_delete_target_batched()`` uncaught by
        ``_do_run_retention_cleanup()``'s per-target failure handling, aborting the entire
        cleanup run.
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
        assert await count_rows(db, "executions", source_tier="framework") == 0

        # The app-tier target was not aborted by the framework target's probe failure.
        assert await count_rows(db, "executions", source_tier="app") == 0

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

        record = make_log_record(lineno=1, msg="test message")
        # Stamp required attributes
        record.seq = 1  # pyright: ignore[reportAttributeAccessIssue]
        record.app_key = None  # pyright: ignore[reportAttributeAccessIssue]
        record.instance_name = None  # pyright: ignore[reportAttributeAccessIssue]
        record.instance_index = None  # pyright: ignore[reportAttributeAccessIssue]
        record.execution_id = None  # pyright: ignore[reportAttributeAccessIssue]

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
        debug_record = make_log_record(level=logging.DEBUG, lineno=1, msg="debug msg")
        handler.emit(debug_record)
        handler.flush_if_pending()

        # No enqueue because it was filtered before accumulation
        assert handler.db_write_queue_drops == 0
        assert handler._batch == []  # pyright: ignore[reportPrivateUsage]
