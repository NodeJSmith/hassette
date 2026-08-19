"""Tests for LogPersistenceHandler batching/flush and the dequeue-timeout flush path.

Complements test_logging_setup.py (renderers, basic logging, noisy-library suppression),
test_logging_correlation.py (correlation filter, seq, execution_id), and
test_logging_capture_handler.py (LogCaptureHandler, queue handler pipeline).
"""

import asyncio
import logging
import queue
import time
from collections.abc import Coroutine
from typing import Any
from unittest.mock import MagicMock

from hassette.logging_ import HassetteQueueListener, LogPersistenceHandler


def _make_dropping_db_service() -> MagicMock:
    """Return a db_service mock whose enqueue() always returns False (simulates full queue)."""
    db_service = MagicMock()
    db_service._insert_log_records = MagicMock(return_value=MagicMock())

    def drop_enqueue(coro: Coroutine[Any, Any, Any]) -> bool:
        coro.close()
        return False

    db_service.enqueue = MagicMock(side_effect=drop_enqueue)
    return db_service


class TestLogPersistenceHandlerBatching:
    """LogPersistenceHandler batches records and flushes at threshold."""

    def test_batch_flushes_at_50_records(self) -> None:
        """Batch is flushed when it reaches BATCH_SIZE (50)."""
        loop = asyncio.new_event_loop()
        db_service = _make_dropping_db_service()
        handler = LogPersistenceHandler(db_service, loop, persistence_level=logging.DEBUG)
        try:
            for i in range(50):
                record = logging.LogRecord("test", logging.INFO, "", 0, f"msg{i}", (), None)
                handler.emit(record)

            # enqueue() returns False → all 50 dropped after flush
            loop.run_until_complete(asyncio.sleep(0))
            assert handler.db_write_queue_drops == 50
            assert len(handler._batch) == 0
        finally:
            loop.close()

    def test_batch_does_not_flush_below_threshold(self) -> None:
        """Batch accumulates below BATCH_SIZE without flushing."""
        loop = asyncio.new_event_loop()
        db_service = MagicMock()
        db_service.enqueue = MagicMock(return_value=True)
        db_service._insert_log_records = MagicMock(return_value=MagicMock())
        handler = LogPersistenceHandler(db_service, loop, persistence_level=logging.DEBUG)
        try:
            for i in range(49):
                record = logging.LogRecord("test", logging.INFO, "", 0, f"msg{i}", (), None)
                handler.emit(record)

            assert handler.db_write_queue_drops == 0
            assert len(handler._batch) == 49
        finally:
            loop.close()

    def test_flush_if_pending_drains_partial_batch(self) -> None:
        """flush_if_pending() drains a partial batch."""
        loop = asyncio.new_event_loop()
        db_service = _make_dropping_db_service()
        handler = LogPersistenceHandler(db_service, loop, persistence_level=logging.DEBUG)
        try:
            for i in range(10):
                record = logging.LogRecord("test", logging.INFO, "", 0, f"msg{i}", (), None)
                handler.emit(record)

            handler.flush_if_pending()
            loop.run_until_complete(asyncio.sleep(0))
            assert handler.db_write_queue_drops == 10
            assert len(handler._batch) == 0
        finally:
            loop.close()

    def test_drops_records_on_queue_full(self) -> None:
        """Records are counted as dropped when enqueue() returns False (queue full)."""
        loop = asyncio.new_event_loop()
        db_service = _make_dropping_db_service()
        handler = LogPersistenceHandler(db_service, loop, persistence_level=logging.DEBUG)
        try:
            assert handler.db_write_queue_drops == 0

            for i in range(100):
                record = logging.LogRecord("test", logging.INFO, "", 0, f"msg{i}", (), None)
                handler.emit(record)

            handler.flush_if_pending()
            loop.run_until_complete(asyncio.sleep(0))
            assert handler.db_write_queue_drops == 100
        finally:
            loop.close()

    def test_skips_records_below_persistence_level(self) -> None:
        """Records below persistence_level are not batched."""
        loop = asyncio.new_event_loop()
        db_service = MagicMock()
        handler = LogPersistenceHandler(db_service, loop, persistence_level=logging.WARNING)
        try:
            record = logging.LogRecord("test", logging.INFO, "", 0, "debug msg", (), None)
            handler.emit(record)

            assert len(handler._batch) == 0
            assert handler.db_write_queue_drops == 0
        finally:
            loop.close()

    def test_close_flushes_pending(self) -> None:
        """close() calls flush_if_pending() before closing."""
        loop = asyncio.new_event_loop()
        db_service = _make_dropping_db_service()
        handler = LogPersistenceHandler(db_service, loop, persistence_level=logging.DEBUG)
        try:
            for i in range(5):
                record = logging.LogRecord("test", logging.INFO, "", 0, f"msg{i}", (), None)
                handler.emit(record)

            handler.close()
            loop.run_until_complete(asyncio.sleep(0))
            assert handler.db_write_queue_drops == 5
            assert len(handler._batch) == 0
        finally:
            loop.close()

    def test_flush_on_closed_loop_counts_dropped(self) -> None:
        """_flush() with a closed event loop counts records as dropped instead of raising."""
        loop = asyncio.new_event_loop()
        db_service = _make_dropping_db_service()
        handler = LogPersistenceHandler(db_service, loop, persistence_level=logging.DEBUG)

        for i in range(3):
            record = logging.LogRecord("test", logging.INFO, "", 0, f"msg{i}", (), None)
            handler.emit(record)

        loop.close()
        handler.close()

        assert handler.db_write_queue_drops == 3
        assert len(handler._batch) == 0


class TestLogPersistenceDropCountWithDB:
    """LogPersistenceHandler counts drops caused by DB queue-full backpressure."""

    @staticmethod
    def enqueue_returning_false(coro: Coroutine[Any, Any, Any]) -> bool:
        coro.close()
        return False

    @staticmethod
    def enqueue_raising_runtime_error(coro: Coroutine[Any, Any, Any]) -> bool:
        coro.close()
        raise RuntimeError("DB shut down")

    def test_db_write_queue_drops_increments_on_enqueue_failure(self) -> None:
        """When enqueue() returns False (queue full), db_write_queue_drops increases."""
        loop = asyncio.new_event_loop()
        db_service = MagicMock()
        db_service._insert_log_records = MagicMock(return_value=MagicMock())
        db_service.enqueue = MagicMock(side_effect=self.enqueue_returning_false)
        handler = LogPersistenceHandler(db_service, loop, persistence_level=logging.DEBUG)
        try:
            for i in range(50):
                record = logging.LogRecord("test", logging.INFO, "", 0, f"msg{i}", (), None)
                handler.emit(record)

            loop.run_until_complete(asyncio.sleep(0))

            assert handler.db_write_queue_drops == 50
        finally:
            loop.close()

    def test_db_write_queue_drops_increments_on_db_shutdown_runtime_error(self) -> None:
        """When enqueue() raises RuntimeError (DB shut down), db_write_queue_drops increases."""
        loop = asyncio.new_event_loop()
        db_service = MagicMock()
        db_service._insert_log_records = MagicMock(return_value=MagicMock())
        db_service.enqueue = MagicMock(side_effect=self.enqueue_raising_runtime_error)
        handler = LogPersistenceHandler(db_service, loop, persistence_level=logging.DEBUG)
        try:
            for i in range(50):
                record = logging.LogRecord("test", logging.INFO, "", 0, f"msg{i}", (), None)
                handler.emit(record)

            loop.run_until_complete(asyncio.sleep(0))

            assert handler.db_write_queue_drops == 50
        finally:
            loop.close()


class TestDequeueTimeoutFlush:
    """HassetteQueueListener dequeue-timeout triggers flush_if_pending on idle."""

    def test_dequeue_timeout_triggers_flush_if_pending(self) -> None:
        """After 200ms idle, the listener thread calls flush_if_pending on handlers."""
        q: queue.Queue[logging.LogRecord] = queue.Queue()
        loop = asyncio.new_event_loop()
        db_service = _make_dropping_db_service()
        persistence = LogPersistenceHandler(db_service, loop, persistence_level=logging.DEBUG)

        listener = HassetteQueueListener(q, persistence)
        listener.start()

        # Enqueue a single record (below BATCH_SIZE, won't auto-flush)
        record = logging.LogRecord("test", logging.WARNING, "", 0, "timeout test", (), None)
        q.put(record)

        # Wait for the dequeue-timeout cycle to flush (200ms timeout + processing)
        time.sleep(0.5)

        listener.stop()
        loop.run_until_complete(asyncio.sleep(0))
        loop.close()

        # The record was flushed by the timeout, then dropped (enqueue returns False)
        assert persistence.db_write_queue_drops == 1
        assert len(persistence._batch) == 0
