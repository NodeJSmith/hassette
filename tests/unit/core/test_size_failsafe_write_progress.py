"""Unit tests for the size failsafe's contribution to ``DatabaseService._write_progress_count``."""

import sqlite3
import time
from typing import Any
from unittest.mock import MagicMock

import aiosqlite
import pytest

from hassette.core.database_service import DatabaseService

from ._fixtures_retention import (
    SOURCE_TIER_APP,
    SOURCE_TIER_FRAMEWORK,
    count_rows,
    db,
    insert_tiered_execution,
    mock_hassette_for_db,
    retention_service,
    run_size_failsafe,
)

__all__ = ["db", "mock_hassette_for_db", "retention_service"]  # re-exposed as fixtures


async def test_size_failsafe_advances_write_progress_once_per_successful_delete(
    retention_service: DatabaseService,
    mock_hassette_for_db: MagicMock,
    db: aiosqlite.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every DELETE that executes advances the counter by exactly one; a DELETE that raises does not."""
    retention_service.hassette.config.database.size_failsafe_delete_batch = 2
    retention_service.hassette.config.database.size_failsafe_max_iterations = 10
    now = time.time()
    await insert_tiered_execution(db, now - 10, SOURCE_TIER_FRAMEWORK)
    for i in range(5):
        await insert_tiered_execution(db, now - i, SOURCE_TIER_APP)
    await db.commit()

    original_execute = db.execute
    outcomes: list[bool] = []

    async def counting_execute(sql: str, *args: Any, **kwargs: Any) -> Any:
        if not sql.strip().startswith("DELETE"):
            return await original_execute(sql, *args, **kwargs)
        if args and args[0] and SOURCE_TIER_FRAMEWORK in args[0]:
            outcomes.append(False)
            raise sqlite3.OperationalError("simulated failure")
        result = await original_execute(sql, *args, **kwargs)
        outcomes.append(True)
        return result

    monkeypatch.setattr(db, "execute", counting_execute)
    before = retention_service._write_progress_count  # pyright: ignore[reportPrivateUsage]

    await run_size_failsafe(retention_service, mock_hassette_for_db)

    assert await count_rows(db, "executions", source_tier="app") == 0
    assert outcomes.count(False) == 1
    assert outcomes.count(True) >= 3  # the 5 app rows alone take three 2-row batches
    assert retention_service._write_progress_count == before + outcomes.count(True)  # pyright: ignore[reportPrivateUsage]
