"""DatabaseService's log-and-continue handlers recover from storage errors and let anything else propagate."""

import asyncio
import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hassette.core import database_service as database_service_module
from hassette.core.database_service import DatabaseService
from hassette.core.database_sql import safe_rollback
from tests.unit.core._fixtures_database_service import initialized_service_with_worker, service

__all__ = ["initialized_service_with_worker", "service"]  # re-exposed as fixtures

STARTUP_BUDGET_FRACTION = 0.001
"""Shrinks the startup catch-up budget so the timeout path fires within milliseconds."""


async def hang(*_args: object) -> None:
    await asyncio.Event().wait()


async def test_shutdown_drain_storage_error_closes_connections(
    initialized_service_with_worker: DatabaseService,
) -> None:
    # No database call in on_shutdown()'s try block raises today, so the handler is reached by
    # failing the drain itself; the test pins which exceptions that handler absorbs.
    service = initialized_service_with_worker
    conn = service._db
    assert isinstance(conn, AsyncMock)

    with patch.object(service, "drain_write_queue", AsyncMock(side_effect=sqlite3.OperationalError("disk I/O error"))):
        await service.on_shutdown()

    conn.close.assert_awaited()
    assert service._db_worker_task is None


async def test_shutdown_drain_programming_error_propagates(
    initialized_service_with_worker: DatabaseService,
) -> None:
    service = initialized_service_with_worker
    conn = service._db
    assert isinstance(conn, AsyncMock)

    with (
        patch.object(service, "drain_write_queue", AsyncMock(side_effect=KeyError("bug"))),
        pytest.raises(KeyError),
    ):
        await service.on_shutdown()

    # The finally block still tears the worker and connections down.
    conn.close.assert_awaited()
    assert service._db_worker_task is None


async def test_startup_cleanup_storage_error_rolls_back_and_continues(service: DatabaseService) -> None:
    service._db = AsyncMock()
    service._db.execute.side_effect = sqlite3.OperationalError("locked")

    await service.catch_up_cleanup_at_startup()

    service._db.rollback.assert_awaited_once()


async def test_startup_cleanup_programming_error_propagates(service: DatabaseService) -> None:
    service._db = AsyncMock()
    service._db.execute.side_effect = AttributeError("bug")

    with pytest.raises(AttributeError):
        await service.catch_up_cleanup_at_startup()


async def test_startup_cleanup_interrupt_storage_error_still_rolls_back(service: DatabaseService) -> None:
    service._db = AsyncMock()
    service._db.execute.side_effect = hang
    service._db.interrupt.side_effect = sqlite3.OperationalError("connection closed")

    with patch.object(database_service_module, "_STARTUP_CLEANUP_BUDGET_FRACTION", STARTUP_BUDGET_FRACTION):
        await asyncio.wait_for(service.catch_up_cleanup_at_startup(), timeout=5.0)

    service._db.interrupt.assert_awaited_once()
    service._db.rollback.assert_awaited_once()


async def test_startup_cleanup_interrupt_programming_error_propagates(service: DatabaseService) -> None:
    service._db = AsyncMock()
    service._db.execute.side_effect = hang
    service._db.interrupt.side_effect = TypeError("bug")

    with (
        patch.object(database_service_module, "_STARTUP_CLEANUP_BUDGET_FRACTION", STARTUP_BUDGET_FRACTION),
        pytest.raises(TypeError),
    ):
        await asyncio.wait_for(service.catch_up_cleanup_at_startup(), timeout=5.0)


async def test_safe_rollback_storage_error_is_absorbed() -> None:
    db = AsyncMock()
    db.rollback.side_effect = sqlite3.OperationalError("rollback failed")

    await safe_rollback(db, MagicMock(), "test")

    db.rollback.assert_awaited_once()


async def test_safe_rollback_programming_error_propagates() -> None:
    db = AsyncMock()
    db.rollback.side_effect = RuntimeError("bug")

    with pytest.raises(RuntimeError, match="bug"):
        await safe_rollback(db, MagicMock(), "test")
