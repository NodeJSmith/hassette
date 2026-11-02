"""Read timeouts against a real connection whose worker thread is stuck on a slow statement."""

import asyncio
import threading
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from unittest.mock import MagicMock

import aiosqlite
import pytest

from hassette.core.telemetry.query_service import TelemetryQueryService
from hassette.exceptions import TelemetryUnavailableError

from .helpers import BASE_TS, DbFixture, insert_invocation, insert_listener

READ_TIMEOUT_SECONDS = 0.1
STALL_LIMIT_SECONDS = 5.0
"""The stalled statement ends by itself after this long, so code that waits for it fails rather than hangs."""

StallWorker = Callable[[], asyncio.Task[aiosqlite.Cursor]]


@pytest.fixture
def release_stall() -> threading.Event:
    """Set to end the stalled statement early."""
    return threading.Event()


@pytest.fixture
async def stall_worker(
    db: DbFixture, db_hassette: MagicMock, monkeypatch: pytest.MonkeyPatch, release_stall: threading.Event
) -> AsyncIterator[StallWorker]:
    """Give the service a short read timeout, and a function that occupies the connection's worker thread."""
    db_svc, _ = db
    monkeypatch.setattr(db_hassette.config.database, "read_timeout_seconds", READ_TIMEOUT_SECONDS)
    await db_svc.read_db.create_function("stall", 0, lambda: release_stall.wait(STALL_LIMIT_SECONDS))
    stalls: list[asyncio.Task[aiosqlite.Cursor]] = []

    def stall() -> asyncio.Task[aiosqlite.Cursor]:
        stalls.append(asyncio.create_task(db_svc.read_db.execute("SELECT stall()")))
        return stalls[-1]

    yield stall

    release_stall.set()
    await asyncio.gather(*stalls)


async def test_summary_snapshot_times_out_without_waiting_for_its_rollback(
    query_service: TelemetryQueryService, db: DbFixture, stall_worker: StallWorker, release_stall: threading.Event
) -> None:
    """The timeout bounds the whole read, and the queued rollback still closes the snapshot afterward."""
    db_svc, _ = db
    stalled = stall_worker()

    with pytest.raises(TelemetryUnavailableError):
        await query_service.get_all_app_summaries(since=BASE_TS, source_tier="app")

    assert not stalled.done()
    release_stall.set()
    await stalled
    # Runs behind every statement the timed-out read queued, so the rollback has been applied by now.
    await query_service.check_health()
    assert not db_svc.read_db.in_transaction


async def test_summary_snapshot_times_out_without_waiting_for_its_cursor_close(
    query_service: TelemetryQueryService,
    db: DbFixture,
    stall_worker: StallWorker,
    release_stall: threading.Event,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stall that begins after a snapshot cursor opens is bounded, as a sibling read on the connection can cause."""
    db_svc, _ = db
    stalls: list[asyncio.Task[aiosqlite.Cursor]] = []
    fetchall = aiosqlite.Cursor.fetchall

    async def stall_before_first_fetch(cursor: aiosqlite.Cursor) -> Iterable[aiosqlite.Row]:
        if not stalls:
            stalls.append(stall_worker())
            await asyncio.sleep(0)  # the stall's first step queues it ahead of the fetch
        return await fetchall(cursor)

    monkeypatch.setattr(aiosqlite.Cursor, "fetchall", stall_before_first_fetch)

    with pytest.raises(TelemetryUnavailableError):
        await query_service.get_all_app_summaries(since=BASE_TS, source_tier="app")

    assert not stalls[0].done()
    release_stall.set()
    await stalls[0]
    # Runs behind every statement the timed-out read queued, so the rollback has been applied by now.
    await query_service.check_health()
    assert not db_svc.read_db.in_transaction


async def test_execute_times_out_without_waiting_for_its_cursor_close(
    query_service: TelemetryQueryService, stall_worker: StallWorker
) -> None:
    """A stall that begins after the cursor opens is bounded too, not only one during the statement itself."""
    stalls: list[asyncio.Task[aiosqlite.Cursor]] = []

    async def read_with_stall_after_open() -> None:
        async with query_service.execute("SELECT 1") as cursor:
            stalls.append(stall_worker())
            await asyncio.sleep(0)  # the stall's first step queues it ahead of the fetch
            await cursor.fetchall()

    with pytest.raises(TelemetryUnavailableError):
        await read_with_stall_after_open()

    assert not stalls[0].done()


async def test_grid_enrichments_read_correctly_when_run_concurrently(
    query_service: TelemetryQueryService, db: DbFixture
) -> None:
    """Statements interleaved with the summary snapshot on one connection match the same reads run in sequence."""
    db_svc, session_id = db
    listener_id = await insert_listener(db_svc, app_key="my_app")
    await insert_invocation(db_svc, listener_id, session_id, status="error", execution_start_ts=BASE_TS + 1)

    def reads() -> list[Awaitable[object]]:
        return [
            query_service.get_all_app_summaries(since=BASE_TS, source_tier="app"),
            query_service.get_per_app_activity_buckets(BASE_TS, BASE_TS + 10, num_buckets=5, source_tier="app"),
            query_service.get_per_app_last_errors(since=BASE_TS, source_tier="app"),
            query_service.get_blocking_event_counts(since=BASE_TS),
        ]

    sequential = [await read for read in reads()]

    # Repeated because the interleaving depends on how the worker thread's queue fills.
    for _ in range(20):
        assert await asyncio.gather(*reads()) == sequential
    assert not db_svc.read_db.in_transaction
