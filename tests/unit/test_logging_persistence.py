"""Tests for LogPersistenceHandler batching/flush and the dequeue-timeout flush path.

Complements test_logging_setup.py (renderers, basic logging, noisy-library suppression),
test_logging_correlation.py (correlation filter, seq, execution_id), and
test_logging_capture_handler.py (LogCaptureHandler, queue handler pipeline).
"""

import asyncio
import logging
import queue
import time
from collections.abc import Callable, Coroutine, Generator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock

from hassette.logging_ import DEQUEUE_TIMEOUT_SECONDS, HassetteQueueListener, LogPersistenceHandler
from tests.support.factories import make_log_record


def _enqueue_returning_false(coro: Coroutine[Any, Any, Any]) -> bool:
    """Stand in for a full DB write queue: refuse the coroutine and report the drop."""
    coro.close()
    return False


def _enqueue_raising_runtime_error(coro: Coroutine[Any, Any, Any]) -> bool:
    """Stand in for a shut-down DB service: refuse the coroutine and raise."""
    coro.close()
    raise RuntimeError("DB shut down")


def _make_dropping_db_service(
    enqueue_side_effect: Callable[[Coroutine[Any, Any, Any]], bool] = _enqueue_returning_false,
) -> MagicMock:
    """Return a db_service mock whose enqueue() refuses coroutines, so emitted records are dropped.

    Defaults to simulating a full queue (enqueue returns False). Pass
    _enqueue_raising_runtime_error to simulate a shut-down service instead.
    """
    db_service = MagicMock()
    db_service._insert_log_records = MagicMock(return_value=MagicMock())
    db_service.enqueue = MagicMock(side_effect=enqueue_side_effect)
    return db_service


@contextmanager
def _persistence_handler(
    db_service: MagicMock | None = None,
    *,
    persistence_level: int = logging.DEBUG,
) -> Generator[tuple[LogPersistenceHandler, asyncio.AbstractEventLoop], None, None]:
    """Set up a LogPersistenceHandler with a throwaway event loop.

    Yields ``(handler, loop)``. One test (``test_flush_on_closed_loop_counts_dropped``)
    intentionally closes the loop before the contextmanager exits — the ``is_closed()``
    guard in ``finally`` tolerates that. Another test (``test_dequeue_timeout_triggers_flush_if_pending``)
    manages the loop entirely on its own because it also needs a ``HassetteQueueListener``.
    """
    loop = asyncio.new_event_loop()
    if db_service is None:
        db_service = _make_dropping_db_service()
    handler = LogPersistenceHandler(db_service, loop, persistence_level=persistence_level)
    try:
        yield handler, loop
    finally:
        if not loop.is_closed():
            loop.close()


def _emit_records(handler: LogPersistenceHandler, count: int) -> None:
    """Emit ``count`` synthetic log records into ``handler``."""
    for i in range(count):
        handler.emit(make_log_record(msg=f"msg{i}"))


class TestLogPersistenceHandlerBatching:
    """LogPersistenceHandler batches records and flushes at threshold."""

    def test_batch_flushes_at_batch_size_records(self) -> None:
        """Batch is flushed when it reaches BATCH_SIZE."""
        with _persistence_handler() as (handler, loop):
            _emit_records(handler, LogPersistenceHandler.BATCH_SIZE)

            # enqueue() returns False → the whole batch is dropped after flush
            loop.run_until_complete(asyncio.sleep(0))
            assert handler.db_write_queue_drops == LogPersistenceHandler.BATCH_SIZE
            assert len(handler._batch) == 0

    def test_batch_does_not_flush_below_threshold(self) -> None:
        """Batch accumulates at one record below BATCH_SIZE without flushing."""
        db_service = MagicMock()
        db_service.enqueue = MagicMock(return_value=True)
        db_service._insert_log_records = MagicMock(return_value=MagicMock())
        with _persistence_handler(db_service) as (handler, _loop):
            _emit_records(handler, LogPersistenceHandler.BATCH_SIZE - 1)

            assert handler.db_write_queue_drops == 0
            assert len(handler._batch) == LogPersistenceHandler.BATCH_SIZE - 1

    def test_flush_if_pending_drains_partial_batch(self) -> None:
        """flush_if_pending() drains a partial batch."""
        with _persistence_handler() as (handler, loop):
            _emit_records(handler, 10)

            handler.flush_if_pending()
            loop.run_until_complete(asyncio.sleep(0))
            assert handler.db_write_queue_drops == 10
            assert len(handler._batch) == 0

    def test_drops_records_on_queue_full(self) -> None:
        """Records are counted as dropped when enqueue() returns False (queue full)."""
        with _persistence_handler() as (handler, loop):
            assert handler.db_write_queue_drops == 0

            _emit_records(handler, 100)

            handler.flush_if_pending()
            loop.run_until_complete(asyncio.sleep(0))
            assert handler.db_write_queue_drops == 100

    def test_skips_records_below_persistence_level(self) -> None:
        """Records below persistence_level are not batched."""
        db_service = MagicMock()
        with _persistence_handler(db_service, persistence_level=logging.WARNING) as (handler, _loop):
            handler.emit(make_log_record(msg="debug msg"))

            assert len(handler._batch) == 0
            assert handler.db_write_queue_drops == 0

    def test_close_flushes_pending(self) -> None:
        """close() calls flush_if_pending() before closing."""
        with _persistence_handler() as (handler, loop):
            _emit_records(handler, 5)

            handler.close()
            loop.run_until_complete(asyncio.sleep(0))
            assert handler.db_write_queue_drops == 5
            assert len(handler._batch) == 0

    def test_flush_on_closed_loop_counts_dropped(self) -> None:
        """_flush() with a closed event loop counts records as dropped instead of raising."""
        with _persistence_handler() as (handler, loop):
            _emit_records(handler, 3)

            loop.close()
            handler.close()

            assert handler.db_write_queue_drops == 3
            assert len(handler._batch) == 0


class TestLogPersistenceDropCountWithDB:
    """LogPersistenceHandler counts drops caused by DB queue-full backpressure."""

    def test_db_write_queue_drops_increments_on_enqueue_failure(self) -> None:
        """When enqueue() returns False (queue full), db_write_queue_drops increases."""
        with _persistence_handler() as (handler, loop):
            _emit_records(handler, LogPersistenceHandler.BATCH_SIZE)

            loop.run_until_complete(asyncio.sleep(0))

            assert handler.db_write_queue_drops == LogPersistenceHandler.BATCH_SIZE

    def test_db_write_queue_drops_increments_on_db_shutdown_runtime_error(self) -> None:
        """When enqueue() raises RuntimeError (DB shut down), db_write_queue_drops increases."""
        db_service = _make_dropping_db_service(_enqueue_raising_runtime_error)
        with _persistence_handler(db_service) as (handler, loop):
            _emit_records(handler, LogPersistenceHandler.BATCH_SIZE)

            loop.run_until_complete(asyncio.sleep(0))

            assert handler.db_write_queue_drops == LogPersistenceHandler.BATCH_SIZE


class TestDequeueTimeoutFlush:
    """HassetteQueueListener dequeue-timeout triggers flush_if_pending on idle."""

    def test_dequeue_timeout_triggers_flush_if_pending(self) -> None:
        """After DEQUEUE_TIMEOUT_SECONDS idle, the listener thread calls flush_if_pending on handlers."""
        # Does not use _persistence_handler: the loop must close after listener.stop()
        # but before assertions, which doesn't fit the contextmanager's finally cleanup.
        q: queue.Queue[logging.LogRecord] = queue.Queue()
        loop = asyncio.new_event_loop()
        db_service = _make_dropping_db_service()
        persistence = LogPersistenceHandler(db_service, loop, persistence_level=logging.DEBUG)

        listener = HassetteQueueListener(q, persistence)
        listener.start()

        # Enqueue a single record (below BATCH_SIZE, won't auto-flush)
        q.put(make_log_record(level=logging.WARNING, msg="timeout test"))

        # Wait for the dequeue-timeout cycle to flush, with margin for thread scheduling
        time.sleep(DEQUEUE_TIMEOUT_SECONDS + 0.3)

        listener.stop()
        loop.run_until_complete(asyncio.sleep(0))
        loop.close()

        # The record was flushed by the timeout, then dropped (enqueue returns False)
        assert persistence.db_write_queue_drops == 1
        assert len(persistence._batch) == 0
