"""Unit tests for DatabaseService."""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hassette.core.database_service import DatabaseService


@pytest.fixture
def mock_hassette(tmp_path: Path) -> MagicMock:
    """Create a mock Hassette with database config defaults."""
    hassette = MagicMock()
    hassette.config.data_dir = tmp_path
    hassette.config.db_path = None
    hassette.config.db_retention_days = 7
    hassette.config.db_max_size_mb = 500
    hassette.config.db_migration_timeout_seconds = 120
    hassette.config.database_service_log_level = "INFO"
    hassette.config.log_level = "INFO"
    hassette.config.task_bucket_log_level = "INFO"
    hassette.config.resource_shutdown_timeout_seconds = 5
    hassette.config.task_cancellation_timeout_seconds = 5
    hassette.ready_event = asyncio.Event()
    return hassette


@pytest.fixture
def service(mock_hassette: MagicMock) -> DatabaseService:
    """Create a DatabaseService instance."""
    return DatabaseService(mock_hassette, parent=mock_hassette)


@pytest.fixture
async def initialized_service_with_worker(service: DatabaseService) -> AsyncIterator[DatabaseService]:
    """Initialize DatabaseService with the worker running; cancel worker in cleanup.

    Does NOT call on_shutdown — leaves worker task and connection management to the test.
    """
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_conn.commit = AsyncMock()
    mock_conn.close = AsyncMock()

    async def fake_connect(*_args: object, **_kwargs: object) -> AsyncMock:
        return mock_conn

    with (
        patch.object(service, "_run_migrations"),
        patch("aiosqlite.connect", side_effect=fake_connect),
    ):
        await service.on_initialize()
    try:
        yield service
    finally:
        if service._db_worker_task is not None and not service._db_worker_task.done():
            service._db_worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await service._db_worker_task


def test_init_sets_defaults(service: DatabaseService) -> None:
    """Constructor sets _db, _db_path, and failure counter to initial values."""
    assert service._db is None
    assert service._db_path == Path()
    assert service._consecutive_heartbeat_failures == 0


def test_config_log_level_delegates_to_config(service: DatabaseService) -> None:
    """config_log_level returns the value from hassette config."""
    service.hassette.config.database_service_log_level = "DEBUG"
    assert service.config_log_level == "DEBUG"


def test_db_property_raises_when_uninitialized(service: DatabaseService) -> None:
    """Accessing db before initialization raises RuntimeError."""
    with pytest.raises(RuntimeError, match="Database connection is not initialized"):
        _ = service.db


def test_resolve_db_path_uses_config_when_set(service: DatabaseService) -> None:
    """When db_path is configured, use it directly."""
    service.hassette.config.db_path = Path("/custom/path/my.db")
    result = service._resolve_db_path()
    assert result == Path("/custom/path/my.db").resolve()


def test_resolve_db_path_defaults_to_data_dir(service: DatabaseService, tmp_path: Path) -> None:
    """When db_path is None, default to data_dir / hassette.db."""
    service.hassette.config.db_path = None
    service.hassette.config.data_dir = tmp_path
    result = service._resolve_db_path()
    assert result == tmp_path / "hassette.db"


def test_init_sets_worker_fields_to_none(service: DatabaseService) -> None:
    """Constructor sets _db_write_queue and _db_worker_task to None."""
    assert service._db_write_queue is None
    assert service._db_worker_task is None


async def test_worker_not_started_before_initialize(service: DatabaseService) -> None:
    """Before on_initialize, _db_worker_task is None."""
    assert service._db_worker_task is None


async def test_worker_started_after_initialize(
    initialized_service_with_worker: DatabaseService,
) -> None:
    """After on_initialize, _db_worker_task is a running Task."""
    task = initialized_service_with_worker._db_worker_task
    assert task is not None
    assert isinstance(task, asyncio.Task)
    assert not task.done()


async def test_submit_returns_coroutine_result(
    initialized_service_with_worker: DatabaseService,
) -> None:
    """submit() returns the value produced by the submitted coroutine."""

    async def coro() -> int:
        return 42

    result = await initialized_service_with_worker.submit(coro())
    assert result == 42


async def test_submit_propagates_coroutine_exception(
    initialized_service_with_worker: DatabaseService,
) -> None:
    """submit() re-raises the exception from a failing coroutine at the await site."""

    class SentinelError(Exception):
        pass

    async def failing_coro() -> None:
        raise SentinelError("boom")

    with pytest.raises(SentinelError, match="boom"):
        await initialized_service_with_worker.submit(failing_coro())


async def test_enqueue_is_fire_and_forget(
    initialized_service_with_worker: DatabaseService,
) -> None:
    """enqueue() returns synchronously; the coroutine completes asynchronously."""
    completed: list[int] = []

    async def coro() -> None:
        completed.append(1)

    # enqueue() must return immediately (it is synchronous)
    initialized_service_with_worker.enqueue(coro())

    # Coroutine should not have run yet (worker hasn't been awaited)
    # After draining the queue, it should have run
    assert initialized_service_with_worker._db_write_queue is not None
    await initialized_service_with_worker._db_write_queue.join()
    assert completed == [1]


async def test_db_max_size_mb_zero_disables_failsafe(
    initialized_service_with_worker: DatabaseService,
) -> None:
    """_check_size_failsafe() returns immediately when db_max_size_mb is 0."""
    initialized_service_with_worker.hassette.config.db_max_size_mb = 0

    # Patch _get_db_size_mb to prove it's never called — the early return
    # should skip the size check entirely.
    initialized_service_with_worker._get_db_size_mb = MagicMock(  # pyright: ignore[reportAttributeAccessIssue]
        side_effect=AssertionError("_get_db_size_mb should not be called when disabled"),
    )
    await initialized_service_with_worker._check_size_failsafe()
    initialized_service_with_worker._get_db_size_mb.assert_not_called()


async def test_worker_continues_after_enqueue_error(
    initialized_service_with_worker: DatabaseService,
) -> None:
    """Worker processes subsequent items even if an enqueued coroutine raises."""
    completed: list[int] = []

    async def failing_coro() -> None:
        raise ValueError("intentional failure")

    async def succeeding_coro() -> None:
        completed.append(1)

    initialized_service_with_worker.enqueue(failing_coro())
    initialized_service_with_worker.enqueue(succeeding_coro())

    assert initialized_service_with_worker._db_write_queue is not None
    await initialized_service_with_worker._db_write_queue.join()
    assert completed == [1]
