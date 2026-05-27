"""Unit tests for LoggingService."""

import asyncio
import logging
import logging.handlers
import queue
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from hassette.core.logging_service import LoggingService
from hassette.logging_ import (
    HassetteQueueListener,
    LogCaptureHandler,
    LogPersistenceHandler,
)
from hassette.test_utils.mock_hassette import make_mock_hassette

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def remove_queue_handlers() -> None:
    """Remove all QueueHandlers from the hassette logger."""
    hassette_logger = logging.getLogger("hassette")
    for h in list(hassette_logger.handlers):
        if isinstance(h, logging.handlers.QueueHandler):
            hassette_logger.removeHandler(h)


def make_db_service() -> MagicMock:
    """Return a minimal DatabaseService mock."""
    db_service = MagicMock()
    db_service.enqueue = Mock(return_value=True)
    db_service._insert_log_records = Mock(return_value=AsyncMock())
    return db_service


def make_logging_service(
    *,
    stream_handler: logging.StreamHandler | None = None,
    hassette: MagicMock | None = None,
) -> LoggingService:
    """Construct a LoggingService with mocked dependencies."""

    if hassette is None:
        hassette = make_mock_hassette(sealed=False)
        hassette.database_service = make_db_service()

    if stream_handler is None:
        stream_handler = logging.StreamHandler()

    # Bypass Resource.__init__ side effects that require a full Hassette tree.
    svc = LoggingService.__new__(LoggingService)
    svc.hassette = hassette
    svc.parent = None
    svc.children = []
    svc.logger = logging.getLogger("hassette.LoggingService")
    # Minimal readiness machinery
    svc._ready_event = asyncio.Event()
    svc._shutdown_event = asyncio.Event()
    svc.shutting_down = False
    svc.initializing = False
    # Wire the stream handler via proper __init__ path but skip super().__init__
    svc._stream_handler = stream_handler
    svc.capture_handler = LogCaptureHandler(buffer_size=hassette.config.web_api.log_buffer_size)
    svc.persistence_handler = None
    svc._queue_listener = None
    svc._queue_handler = None

    svc.mark_ready = Mock()

    return svc


# ---------------------------------------------------------------------------
# Tests: LogPersistenceHandler constructor injection
# ---------------------------------------------------------------------------


class TestLogPersistenceHandlerConstructor:
    """Verify FR#4: constructor injection, no set_database()."""

    def test_constructor_accepts_db_service_and_loop(self) -> None:
        db_service = make_db_service()
        loop = asyncio.new_event_loop()
        try:
            handler = LogPersistenceHandler(db_service, loop)
            assert handler._db_service is db_service
            assert handler._loop is loop
        finally:
            loop.close()

    def test_set_database_method_removed(self) -> None:
        """set_database() must not exist on LogPersistenceHandler."""
        assert not hasattr(LogPersistenceHandler, "set_database"), (
            "set_database() still exists on LogPersistenceHandler — remove it"
        )

    def test_constructor_sets_persistence_level(self) -> None:
        db_service = make_db_service()
        loop = asyncio.new_event_loop()
        try:
            handler = LogPersistenceHandler(db_service, loop, persistence_level=logging.WARNING)
            assert handler._persistence_level == logging.WARNING
        finally:
            loop.close()

    @pytest.mark.asyncio
    async def test_flush_calls_enqueue_on_db_service(self) -> None:
        """After construction, flush() should call db_service.enqueue() — no wiring step."""
        db_service = make_db_service()
        loop = asyncio.get_running_loop()
        handler = LogPersistenceHandler(db_service, loop)

        # Emit a record so there's something to flush
        record = logging.LogRecord("hassette", logging.INFO, "", 0, "test msg", (), None)
        handler.emit(record)
        handler.flush_if_pending()

        # _flush uses call_soon_threadsafe to schedule _do_enqueue on the event loop.
        # Yield to the event loop to allow the scheduled callback to run.
        await asyncio.sleep(0)

        assert db_service.enqueue.called


# ---------------------------------------------------------------------------
# Tests: LoggingService.on_initialize()
# ---------------------------------------------------------------------------


class TestLoggingServiceOnInitialize:
    """Verify FR#1, FR#2, AC#1, AC#2, AC#10."""

    @pytest.mark.asyncio
    async def test_on_initialize_creates_queue_listener_and_starts_it(self) -> None:
        """QueueListener is created and started during on_initialize."""

        hassette = make_mock_hassette(sealed=False)
        hassette.database_service = make_db_service()
        stream_handler = logging.StreamHandler()

        svc = make_logging_service(stream_handler=stream_handler, hassette=hassette)

        started_listeners: list[HassetteQueueListener] = []

        original_start = HassetteQueueListener.start

        def capturing_start(self_listener) -> None:
            started_listeners.append(self_listener)
            original_start(self_listener)

        with patch.object(HassetteQueueListener, "start", capturing_start):
            await svc.on_initialize()

        try:
            assert svc._queue_listener is not None
            assert len(started_listeners) == 1
            assert started_listeners[0] is svc._queue_listener
        finally:
            if svc._queue_listener is not None:
                svc._queue_listener.stop()

    @pytest.mark.asyncio
    async def test_on_initialize_calls_mark_ready(self) -> None:
        """mark_ready() is called after pipeline starts — unconditionally."""

        hassette = make_mock_hassette(sealed=False)
        hassette.database_service = make_db_service()
        svc = make_logging_service(hassette=hassette)

        await svc.on_initialize()

        try:
            svc.mark_ready.assert_called_once()
        finally:
            if svc._queue_listener is not None:
                svc._queue_listener.stop()

    @pytest.mark.asyncio
    async def test_on_initialize_all_three_handlers_attached_to_listener(self) -> None:
        """Stream, capture, and persistence handlers are all in the QueueListener."""

        hassette = make_mock_hassette(sealed=False)
        hassette.database_service = make_db_service()
        svc = make_logging_service(hassette=hassette)

        await svc.on_initialize()

        try:
            assert svc._queue_listener is not None
            handler_types = [type(h) for h in svc._queue_listener.handlers]
            assert logging.StreamHandler in handler_types
            assert LogCaptureHandler in handler_types
            assert LogPersistenceHandler in handler_types
        finally:
            if svc._queue_listener is not None:
                svc._queue_listener.stop()

    @pytest.mark.asyncio
    async def test_on_initialize_persistence_failure_still_starts_pipeline(self) -> None:
        """If persistence handler creation fails, pipeline still starts with stream + capture."""

        hassette = make_mock_hassette(sealed=False)
        hassette.database_service = make_db_service()
        svc = make_logging_service(hassette=hassette)

        with patch(
            "hassette.core.logging_service.LogPersistenceHandler",
            side_effect=RuntimeError("db unavailable"),
        ):
            await svc.on_initialize()

        try:
            assert svc._queue_listener is not None, "Pipeline must start even without persistence"
            assert svc.persistence_handler is None
            # capture and stream handlers still present
            handler_types = [type(h) for h in svc._queue_listener.handlers]
            assert logging.StreamHandler in handler_types
            assert LogCaptureHandler in handler_types
            assert LogPersistenceHandler not in handler_types
            # mark_ready still called
            svc.mark_ready.assert_called_once()
        finally:
            if svc._queue_listener is not None:
                svc._queue_listener.stop()

    @pytest.mark.asyncio
    async def test_on_initialize_swaps_stream_handler_for_queue_handler(self) -> None:
        """After init, the hassette logger uses QueueHandler not StreamHandler."""

        hassette_logger = logging.getLogger("hassette")
        stream_handler = logging.StreamHandler()
        # Put stream handler on logger to simulate Phase 1
        hassette_logger.addHandler(stream_handler)

        hassette = make_mock_hassette(sealed=False)
        hassette.database_service = make_db_service()
        svc = make_logging_service(stream_handler=stream_handler, hassette=hassette)

        await svc.on_initialize()

        try:
            handler_types = [type(h) for h in hassette_logger.handlers]
            assert logging.handlers.QueueHandler in handler_types
            assert stream_handler not in hassette_logger.handlers
        finally:
            if svc._queue_listener is not None:
                svc._queue_listener.stop()
            # Restore logger state
            hassette_logger.removeHandler(svc._queue_handler)
            hassette_logger.addHandler(stream_handler)

    @pytest.mark.asyncio
    async def test_on_initialize_defensive_cleanup_removes_stale_queue_handler(self) -> None:
        """A stale QueueHandler on the logger is removed before the new one is added."""

        hassette_logger = logging.getLogger("hassette")
        stale_q: queue.Queue[logging.LogRecord] = queue.Queue()
        stale_queue_handler = logging.handlers.QueueHandler(stale_q)
        hassette_logger.addHandler(stale_queue_handler)

        hassette = make_mock_hassette(sealed=False)
        hassette.database_service = make_db_service()
        svc = make_logging_service(hassette=hassette)

        await svc.on_initialize()

        try:
            assert stale_queue_handler not in hassette_logger.handlers, (
                "Stale QueueHandler should have been removed by defensive cleanup"
            )
            # Exactly one QueueHandler: the new one
            queue_handlers = [h for h in hassette_logger.handlers if isinstance(h, logging.handlers.QueueHandler)]
            assert len(queue_handlers) == 1
        finally:
            if svc._queue_listener is not None:
                svc._queue_listener.stop()
            remove_queue_handlers()


# ---------------------------------------------------------------------------
# Tests: LoggingService.on_shutdown()
# ---------------------------------------------------------------------------


class TestLoggingServiceOnShutdown:
    """Verify FR#3, AC#3."""

    @pytest.mark.asyncio
    async def test_on_shutdown_stops_listener_and_restores_stream_handler(self) -> None:
        """Shutdown removes QueueHandler, re-adds StreamHandler, stops QueueListener."""
        hassette_logger = logging.getLogger("hassette")
        stream_handler = logging.StreamHandler()
        hassette_logger.addHandler(stream_handler)

        hassette = make_mock_hassette(sealed=False)
        hassette.database_service = make_db_service()
        svc = make_logging_service(stream_handler=stream_handler, hassette=hassette)

        await svc.on_initialize()
        # Record the queue_handler that was installed
        queue_handler = svc._queue_handler

        await svc.on_shutdown()

        try:
            # Stream handler restored
            assert stream_handler in hassette_logger.handlers
            # QueueHandler removed
            assert queue_handler not in hassette_logger.handlers
            # QueueListener stopped (thread should not be alive)
            assert svc._queue_listener is not None
            # After stop(), the listener thread should exit — check its internal thread
            listener_thread = svc._queue_listener._thread  # pyright: ignore[reportAttributeAccessIssue]
            if listener_thread is not None:
                assert not listener_thread.is_alive()
        finally:
            hassette_logger.removeHandler(stream_handler)

    @pytest.mark.asyncio
    async def test_on_shutdown_sets_capture_handler_shutting_down(self) -> None:
        """capture_handler.shutting_down is set to True during shutdown."""
        hassette = make_mock_hassette(sealed=False)
        hassette.database_service = make_db_service()
        svc = make_logging_service(hassette=hassette)

        await svc.on_initialize()
        assert not svc.capture_handler.shutting_down

        await svc.on_shutdown()
        assert svc.capture_handler.shutting_down

        remove_queue_handlers()

    @pytest.mark.asyncio
    async def test_on_shutdown_flushes_persistence_handler(self) -> None:
        """flush_if_pending() is called on persistence_handler during shutdown."""
        hassette = make_mock_hassette(sealed=False)
        hassette.database_service = make_db_service()
        svc = make_logging_service(hassette=hassette)

        await svc.on_initialize()

        assert svc.persistence_handler is not None
        svc.persistence_handler.flush_if_pending = Mock()

        await svc.on_shutdown()

        svc.persistence_handler.flush_if_pending.assert_called_once()

        remove_queue_handlers()


# ---------------------------------------------------------------------------
# Tests: dropped_count property
# ---------------------------------------------------------------------------


class TestDroppedCount:
    """Verify dropped_count delegates to persistence_handler."""

    @pytest.mark.asyncio
    async def test_dropped_count_zero_when_no_persistence_handler(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        hassette.database_service = make_db_service()
        svc = make_logging_service(hassette=hassette)

        # With persistence_handler creation failing, dropped_count should be 0
        with patch(
            "hassette.core.logging_service.LogPersistenceHandler",
            side_effect=RuntimeError("unavailable"),
        ):
            await svc.on_initialize()

        try:
            assert svc.dropped_count == 0
        finally:
            if svc._queue_listener is not None:
                svc._queue_listener.stop()

    @pytest.mark.asyncio
    async def test_dropped_count_reads_from_persistence_handler(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        hassette.database_service = make_db_service()
        svc = make_logging_service(hassette=hassette)

        await svc.on_initialize()

        try:
            assert svc.persistence_handler is not None
            # Manually bump the dropped counter via the lock
            with svc.persistence_handler._dropped_lock:
                svc.persistence_handler._dropped = 7

            assert svc.dropped_count == 7
        finally:
            if svc._queue_listener is not None:
                svc._queue_listener.stop()


# ---------------------------------------------------------------------------
# Tests: sync→async swap — no record loss (FR#6, AC#5)
# ---------------------------------------------------------------------------


class TestSyncToAsyncSwap:
    """Verify no records are lost during the handler swap."""

    @pytest.mark.asyncio
    async def test_records_emitted_before_init_reach_capture_handler(self) -> None:
        """Records emitted via Phase 1 StreamHandler arrive in capture handler after init.

        Simulates: emit N records before on_initialize(), then init, then emit
        M more. Pre-init records land in pre_capture (synchronous); post-init
        records land in svc.capture_handler (async pipeline).
        """
        hassette_logger = logging.getLogger("hassette")

        # Create mocks BEFORE attaching handlers — mock construction can trigger
        # framework logs (e.g. hassette.config.helpers) that would contaminate buffers.
        hassette = make_mock_hassette(sealed=False)
        hassette.database_service = make_db_service()
        stream_handler = logging.StreamHandler()

        pre_capture = LogCaptureHandler(buffer_size=500)
        hassette_logger.addHandler(stream_handler)
        hassette_logger.addHandler(pre_capture)

        svc = make_logging_service(stream_handler=stream_handler, hassette=hassette)

        n = 5
        for i in range(n):
            hassette_logger.warning("pre-init record %d", i)

        pre_init_msgs = [e for e in pre_capture.buffer if e.message.startswith("pre-init record")]
        assert len(pre_init_msgs) == n

        await svc.on_initialize()

        m = 5
        for i in range(n, n + m):
            hassette_logger.warning("post-init record %d", i)

        await asyncio.sleep(0.1)

        try:
            post_init_msgs = [e.message for e in svc.capture_handler.buffer if e.message.startswith("post-init record")]
            assert len(post_init_msgs) == m, (
                f"Expected {m} post-init records in capture handler, got {len(post_init_msgs)}: {post_init_msgs}"
            )
        finally:
            if svc._queue_listener is not None:
                svc._queue_listener.stop()
            hassette_logger.removeHandler(pre_capture)
            remove_queue_handlers()
            hassette_logger.removeHandler(stream_handler)
