"""Characterization tests for a retention target failing partway through its batched delete."""

import logging
import sqlite3
import time
from typing import Any

import aiosqlite
import pytest

from hassette.const.misc import SECONDS_PER_DAY
from hassette.core.database_service import DatabaseService

from .test_log_records_retention import (
    SOURCE_TIER_APP,
    SOURCE_TIER_FRAMEWORK,
    db,
    insert_tiered_execution,
    mock_hassette_for_db,
    retention_service,
)

__all__ = ["db", "mock_hassette_for_db", "retention_service"]  # re-exposed as fixtures

FAILURE_LOG_PREFIX = "Retention cleanup failed for framework executions"


async def test_mid_batch_failure_reports_partial_progress_with_traceback(
    db: aiosqlite.Connection,
    caplog: pytest.LogCaptureFixture,
    retention_service: DatabaseService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DELETE failing on a later batch keeps the rows earlier batches committed, reports them
    in the cleanup summary alongside the failure, and logs the original error's traceback.
    """
    retention_service.hassette.config.database.retention_delete_batch = 2
    retention_service.hassette.config.database.retention_max_batches_per_target = 5

    now = time.time()
    old_framework_ts = now - (5 * SECONDS_PER_DAY)  # older than framework_retention_days=1
    for _ in range(6):
        await insert_tiered_execution(db, old_framework_ts, SOURCE_TIER_FRAMEWORK)
    await insert_tiered_execution(db, now - (10 * SECONDS_PER_DAY), SOURCE_TIER_APP)
    await db.commit()

    # Fail the third executions DELETE: the framework target's third batch, after two
    # 2-row batches have already committed.
    original_execute = db.execute
    delete_calls = 0

    async def fail_third_delete(sql: str, *args: Any, **kwargs: Any) -> Any:
        nonlocal delete_calls
        if "DELETE FROM executions" in sql:
            delete_calls += 1
            if delete_calls == 3:
                raise sqlite3.OperationalError("simulated mid-batch failure")
        return await original_execute(sql, *args, **kwargs)

    monkeypatch.setattr(db, "execute", fail_third_delete)

    with caplog.at_level(logging.INFO):
        await retention_service._do_run_retention_cleanup()  # pyright: ignore[reportPrivateUsage]

    cursor = await db.execute("SELECT COUNT(*) FROM executions WHERE source_tier = 'framework'")
    assert (await cursor.fetchone())[0] == 2  # two committed batches removed 4 of 6 rows

    cursor = await db.execute("SELECT COUNT(*) FROM executions WHERE source_tier = 'app'")
    assert (await cursor.fetchone())[0] == 0  # a later target is unaffected by the failure

    failure_records = [r for r in caplog.records if r.getMessage().startswith(FAILURE_LOG_PREFIX)]
    assert len(failure_records) == 1
    assert failure_records[0].levelno == logging.ERROR
    assert "sqlite3.OperationalError: simulated mid-batch failure" in caplog.text  # traceback rendered

    summary = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("Retention cleanup summary"))
    assert "4 framework executions" in summary
    assert "1 app executions" in summary
    assert "failed: framework executions" in summary
