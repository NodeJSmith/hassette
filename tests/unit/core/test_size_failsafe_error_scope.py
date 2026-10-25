"""The size failsafe recovers from storage errors and lets any other exception propagate."""

import sqlite3
import time
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest

from hassette.core.database_service import DatabaseService

from ._fixtures_retention import (
    SOURCE_TIER_APP,
    db,
    insert_tiered_execution,
    make_failing_execute,
    mock_hassette_for_db,
    retention_service,
    run_size_failsafe,
)

__all__ = ["db", "mock_hassette_for_db", "retention_service"]  # re-exposed as fixtures


async def test_live_size_read_storage_error_returns_none(retention_service: DatabaseService) -> None:
    """A storage error reading the live data size is logged and reported as None."""
    retention_service.get_live_data_size_mb = AsyncMock(  # pyright: ignore[reportAttributeAccessIssue]
        side_effect=sqlite3.OperationalError("simulated failure")
    )

    assert await retention_service.read_live_data_mb_or_none() is None


async def test_live_size_read_non_storage_error_propagates(retention_service: DatabaseService) -> None:
    """A non-storage exception reading the live data size is a bug, not a recoverable failure."""
    retention_service.get_live_data_size_mb = AsyncMock(  # pyright: ignore[reportAttributeAccessIssue]
        side_effect=RuntimeError("programming error")
    )

    with pytest.raises(RuntimeError, match="programming error"):
        await retention_service.read_live_data_mb_or_none()


async def test_failsafe_delete_non_storage_error_propagates(
    retention_service: DatabaseService,
    mock_hassette_for_db: MagicMock,
    db: aiosqlite.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-storage exception from a failsafe DELETE escapes the cycle instead of being logged and skipped."""
    await insert_tiered_execution(db, time.time(), SOURCE_TIER_APP)
    await db.commit()
    monkeypatch.setattr(db, "execute", make_failing_execute(db, "DELETE", RuntimeError("programming error")))

    with pytest.raises(RuntimeError, match="programming error"):
        await run_size_failsafe(retention_service, mock_hassette_for_db)
