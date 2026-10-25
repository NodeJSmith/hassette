"""Characterization tests for a retention target failing partway through its batched delete."""

import sqlite3
import time
from typing import Any

import aiosqlite
import pytest

from hassette.const.misc import SECONDS_PER_DAY
from hassette.core.database_service import DatabaseService
from hassette.core.retention_targets import _RETENTION_TABLES  # pyright: ignore[reportPrivateUsage]

from ._fixtures_retention import (
    SOURCE_TIER_APP,
    SOURCE_TIER_FRAMEWORK,
    count_rows,
    db,
    insert_tiered_execution,
    mock_hassette_for_db,
    retention_service,
)

__all__ = ["db", "mock_hassette_for_db", "retention_service"]  # re-exposed as fixtures

FRAMEWORK_TARGET = next(t for t in _RETENTION_TABLES if t.failsafe_label == "framework executions")


async def seed_and_fail_third_executions_delete(
    retention_service: DatabaseService, db: aiosqlite.Connection, monkeypatch: pytest.MonkeyPatch
) -> sqlite3.OperationalError:
    """Seed 6 stale framework rows and 1 stale app row, then make the third executions DELETE raise.

    With 2-row batches, the framework target's third batch fails after two batches (4 rows) have
    committed. Returns the exception that the patched DELETE raises.
    """
    retention_service.hassette.config.database.retention_delete_batch = 2
    retention_service.hassette.config.database.retention_max_batches_per_target = 5

    now = time.time()
    for _ in range(6):
        await insert_tiered_execution(db, now - (5 * SECONDS_PER_DAY), SOURCE_TIER_FRAMEWORK)
    await insert_tiered_execution(db, now - (10 * SECONDS_PER_DAY), SOURCE_TIER_APP)
    await db.commit()

    failure = sqlite3.OperationalError("simulated mid-batch failure")
    original_execute = db.execute
    delete_calls = 0

    async def fail_third_delete(sql: str, *args: Any, **kwargs: Any) -> Any:
        nonlocal delete_calls
        if "DELETE FROM executions" in sql:
            delete_calls += 1
            if delete_calls == 3:
                raise failure
        return await original_execute(sql, *args, **kwargs)

    monkeypatch.setattr(db, "execute", fail_third_delete)
    return failure


async def test_mid_batch_failure_returns_committed_progress_and_original_error(
    retention_service: DatabaseService,
    db: aiosqlite.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DELETE failing on a later batch returns the rows earlier batches committed plus the original error.

    Only the two committed batches advance the write-progress counter; the failed third does not.
    """
    failure = await seed_and_fail_third_executions_delete(retention_service, db, monkeypatch)
    progress_before = retention_service._write_progress_count  # pyright: ignore[reportPrivateUsage]

    result = await retention_service._delete_target_batched(  # pyright: ignore[reportPrivateUsage]
        FRAMEWORK_TARGET, time.time(), retention_service.hassette.config
    )

    assert result.deleted == 4
    assert result.error is failure
    assert result.exhausted is False
    assert retention_service._write_progress_count == progress_before + 2  # pyright: ignore[reportPrivateUsage]


async def test_mid_batch_failure_keeps_committed_rows_and_continues_later_targets(
    retention_service: DatabaseService,
    db: aiosqlite.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Committed batches stay deleted, a later target still runs, the failure skips the parent-guard, and the
    original exception is handed to the error log as ``exc_info`` (no active ``except`` frame supplies it).
    """
    failure = await seed_and_fail_third_executions_delete(retention_service, db, monkeypatch)
    error_exc_infos: list[object] = []
    original_error = retention_service.logger.error

    def record_error(*args: Any, **kwargs: Any) -> None:
        error_exc_infos.append(kwargs.get("exc_info"))
        original_error(*args, **kwargs)

    monkeypatch.setattr(retention_service.logger, "error", record_error)

    await retention_service._do_run_retention_cleanup()  # pyright: ignore[reportPrivateUsage]

    assert await count_rows(db, "executions", source_tier="framework") == 2  # two committed batches removed 4 of 6 rows

    assert await count_rows(db, "executions", source_tier="app") == 0  # a later target is unaffected by the failure

    assert retention_service._consecutive_parent_guard_skips == 1  # pyright: ignore[reportPrivateUsage]
    assert error_exc_infos == [failure]


async def test_each_committed_batch_advances_write_progress(
    retention_service: DatabaseService,
    db: aiosqlite.Connection,
) -> None:
    """A multi-batch pass advances the counter once per committed batch, including the short final one."""
    retention_service.hassette.config.database.retention_delete_batch = 2
    retention_service.hassette.config.database.retention_max_batches_per_target = 5
    now = time.time()
    for _ in range(5):
        await insert_tiered_execution(db, now - (5 * SECONDS_PER_DAY), SOURCE_TIER_FRAMEWORK)
    await db.commit()
    before = retention_service._write_progress_count  # pyright: ignore[reportPrivateUsage]

    result = await retention_service._delete_target_batched(  # pyright: ignore[reportPrivateUsage]
        FRAMEWORK_TARGET, now, retention_service.hassette.config
    )

    assert result.deleted == 5
    assert retention_service._write_progress_count == before + 3  # pyright: ignore[reportPrivateUsage]


async def test_non_storage_error_from_batch_propagates(
    retention_service: DatabaseService,
    db: aiosqlite.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-storage exception from a batch is a bug: it propagates instead of being returned as the error."""
    await insert_tiered_execution(db, time.time() - (5 * SECONDS_PER_DAY), SOURCE_TIER_FRAMEWORK)
    await db.commit()
    original_execute = db.execute

    async def failing_delete(sql: str, *args: Any, **kwargs: Any) -> Any:
        if "DELETE FROM executions" in sql:
            raise RuntimeError("programming error")
        return await original_execute(sql, *args, **kwargs)

    monkeypatch.setattr(db, "execute", failing_delete)

    with pytest.raises(RuntimeError, match="programming error"):
        await retention_service._delete_target_batched(  # pyright: ignore[reportPrivateUsage]
            FRAMEWORK_TARGET, time.time(), retention_service.hassette.config
        )
