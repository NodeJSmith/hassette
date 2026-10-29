"""Unit tests for LoggingService."""

import asyncio
import logging
import logging.handlers
import queue
from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from hassette.core.logging_service import LoggingService
from hassette.logging_ import (
    LOGGER_NAMES,
    HassetteQueueHandler,
    HassetteQueueListener,
    LogCaptureHandler,
    LogPersistenceHandler,
)
from tests.support.factories import make_log_record, make_recording_log_capture_handler
from tests.support.mock_hassette import make_mock_hassette
from tests.support.task_buckets import sealed_fallback_task_factory

EXTRA_LOGGER_NAME = "my_app.notify"

TrackService = Callable[[LoggingService], LoggingService]


@pytest.fixture
def track_service() -> Iterator[TrackService]:
    """Register LoggingServices for teardown; yields a pass-through ``track(svc) -> svc``.

    After the test, stops every tracked service's QueueListener that is still running and
    restores the handler lists of the hassette, py.warnings, and extra loggers to what they
    were before the test, undoing both the pipeline's QueueHandler swap and any handlers the
    test attached itself.
    """
    loggers = [logging.getLogger(name) for name in (*LOGGER_NAMES, EXTRA_LOGGER_NAME)]
    saved_handlers = {logger: list(logger.handlers) for logger in loggers}
    services: list[LoggingService] = []

    def track(svc: LoggingService) -> LoggingService:
        services.append(svc)
        return svc

    yield track

    for svc in services:
        listener = svc._queue_listener
        # QueueListener.stop() is not idempotent before Python 3.12 — skip already-stopped ones.
        if listener is not None and listener._thread is not None:  # pyright: ignore[reportAttributeAccessIssue]
            listener.stop()
    for logger, handlers in saved_handlers.items():
        for h in list(logger.handlers):
            if h not in handlers:
                logger.removeHandler(h)
        for h in handlers:
            if h not in logger.handlers:
                logger.addHandler(h)


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
    svc._unique_name = "LoggingService.test"
    # Minimal readiness machinery — real Event so the module-level mark_ready()
    # (called by on_initialize()) can operate on this bypassed instance.
    svc.ready_event = asyncio.Event()
    svc._ready_reason = None
    svc.shutdown_event = asyncio.Event()
    svc._init_task = None
    svc._shutdown_task = None
    svc._shutdown_body_task = None
    svc._shutdown_outcome = None
    # Wire the stream handler via proper __init__ path but skip super().__init__
    svc._stream_handler = stream_handler
    svc.capture_handler = LogCaptureHandler()
    svc.persistence_handler = None
    svc._queue_listener = None
    svc._queue_handler = None
    svc._retired_log_queue_drops = 0

    return svc


async def make_initialized_logging_service(**kw) -> LoggingService:
    """Build a LoggingService via make_logging_service() and run on_initialize().

    Kwargs pass straight through to make_logging_service() (stream_handler, hassette) —
    with no hassette given, one is created with a mocked database_service, matching that
    factory's own default.
    """
    svc = make_logging_service(**kw)
    await svc.on_initialize()
    return svc


async def make_logging_service_with_config(**logging_config: Any) -> LoggingService:
    """Initialize a LoggingService against a real LoggingConfig built from ``logging_config``."""
    hassette = make_mock_hassette(sealed=False, logging=logging_config)
    hassette.database_service = make_db_service()
    return await make_initialized_logging_service(hassette=hassette)


class TestLogPersistenceHandlerConstructor:
    """LogPersistenceHandler accepts db_service and loop via constructor; no set_database()."""

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

    async def test_flush_calls_enqueue_on_db_service(self) -> None:
        """After construction, flush() should call db_service.enqueue() — no wiring step."""
        db_service = make_db_service()
        loop = asyncio.get_running_loop()
        handler = LogPersistenceHandler(db_service, loop)

        # Emit a record so there's something to flush
        record = make_log_record(name="hassette", msg="test msg")
        handler.emit(record)
        handler.flush_if_pending()

        # _flush uses call_soon_threadsafe to schedule _do_enqueue on the event loop.
        # Yield to the event loop to allow the scheduled callback to run.
        await asyncio.sleep(0)

        assert db_service.enqueue.called


class TestLoggingServiceOnInitialize:
    """LoggingService.on_initialize creates and starts the async logging pipeline."""

    async def test_on_initialize_creates_queue_listener_and_starts_it(self, track_service: TrackService) -> None:
        """QueueListener is created and started during on_initialize."""
        hassette = make_mock_hassette(sealed=False)
        hassette.database_service = make_db_service()
        stream_handler = logging.StreamHandler()

        svc = track_service(make_logging_service(stream_handler=stream_handler, hassette=hassette))

        started_listeners: list[HassetteQueueListener] = []

        original_start = HassetteQueueListener.start

        def capturing_start(self_listener) -> None:
            started_listeners.append(self_listener)
            original_start(self_listener)

        with patch.object(HassetteQueueListener, "start", capturing_start):
            await svc.on_initialize()

        assert svc._queue_listener is not None
        assert len(started_listeners) == 1
        assert started_listeners[0] is svc._queue_listener

    async def test_on_initialize_calls_mark_ready(self, track_service: TrackService) -> None:
        """mark_ready() is called after pipeline starts — unconditionally."""
        svc = track_service(await make_initialized_logging_service())

        assert svc.is_ready()

    async def test_on_initialize_all_three_handlers_attached_to_listener(self, track_service: TrackService) -> None:
        """Stream, capture, and persistence handlers are all in the QueueListener."""
        svc = track_service(await make_initialized_logging_service())

        assert svc._queue_listener is not None
        handler_types = [type(h) for h in svc._queue_listener.handlers]
        assert logging.StreamHandler in handler_types
        assert LogCaptureHandler in handler_types
        assert LogPersistenceHandler in handler_types

    async def test_on_initialize_persistence_failure_still_starts_pipeline(self, track_service: TrackService) -> None:
        """If persistence handler creation fails, pipeline still starts with stream + capture."""
        hassette = make_mock_hassette(sealed=False)
        hassette.database_service = make_db_service()
        svc = track_service(make_logging_service(hassette=hassette))

        with patch(
            "hassette.core.logging_service.LogPersistenceHandler",
            side_effect=RuntimeError("db unavailable"),
        ):
            await svc.on_initialize()

        assert svc._queue_listener is not None, "Pipeline must start even without persistence"
        assert svc.persistence_handler is None
        # capture and stream handlers still present
        handler_types = [type(h) for h in svc._queue_listener.handlers]
        assert logging.StreamHandler in handler_types
        assert LogCaptureHandler in handler_types
        assert LogPersistenceHandler not in handler_types
        # mark_ready still called
        assert svc.is_ready()

    async def test_on_initialize_persistence_level_follows_log_level(self, track_service: TrackService) -> None:
        """An unset persistence level follows log_level, so DEBUG records stay queryable in the UI."""
        svc = track_service(await make_logging_service_with_config(log_level="DEBUG"))

        assert svc.persistence_handler is not None
        assert svc.persistence_handler._persistence_level == logging.DEBUG

    async def test_on_initialize_keeps_persistence_level_below_log_level(self, track_service: TrackService) -> None:
        """A persistence_level deliberately set lower than log_level is left alone."""
        svc = track_service(await make_logging_service_with_config(log_level="INFO", log_persistence_level="DEBUG"))

        assert svc.persistence_handler is not None
        assert svc.persistence_handler._persistence_level == logging.DEBUG

    async def test_on_initialize_sets_capture_handler_notify_level_to_persistence_level(
        self, track_service: TrackService
    ) -> None:
        """capture_handler's notify floor tracks whatever the persistence handler actually uses.

        Regression coverage: a per-service logger override (e.g. LoggingConfig.scheduler_service)
        or a runtime PUT /logs/level change can let a record through below the global log_level,
        independent of the persistence_level computed here — filtering by this floor at emit()
        time (see LogCaptureHandler) closes that gap for any logger without having to track their
        effective levels in LoggingService itself.
        """
        svc = track_service(await make_logging_service_with_config(log_level="DEBUG"))

        assert svc.persistence_handler is not None
        assert svc.capture_handler._min_notify_level == svc.persistence_handler._persistence_level
        assert svc.capture_handler._min_notify_level == logging.DEBUG

    async def test_on_initialize_disables_notify_when_persistence_handler_creation_fails(
        self, track_service: TrackService
    ) -> None:
        """If persistence can't be created, nothing is persisted — so no hint should ever fire.

        Otherwise the frontend's hint-triggered `/logs/recent` refetch would be told to look for a record
        that can never exist in the database.
        """
        hassette = make_mock_hassette(sealed=False)
        hassette.database_service = make_db_service()
        svc = track_service(make_logging_service(hassette=hassette))

        with patch(
            "hassette.core.logging_service.LogPersistenceHandler",
            side_effect=RuntimeError("db unavailable"),
        ):
            await svc.on_initialize()

        assert svc.persistence_handler is None
        assert svc.capture_handler._min_notify_level > logging.CRITICAL

    async def test_on_initialize_swaps_stream_handler_for_queue_handler(self, track_service: TrackService) -> None:
        """After init, the hassette logger uses QueueHandler not StreamHandler."""
        hassette_logger = logging.getLogger("hassette")
        stream_handler = logging.StreamHandler()
        # Put stream handler on logger to simulate Phase 1
        hassette_logger.addHandler(stream_handler)

        track_service(await make_initialized_logging_service(stream_handler=stream_handler))

        handler_types = [type(h) for h in hassette_logger.handlers]
        assert HassetteQueueHandler in handler_types
        assert stream_handler not in hassette_logger.handlers

    async def test_on_initialize_defensive_cleanup_removes_stale_queue_handler(
        self, track_service: TrackService
    ) -> None:
        """A stale QueueHandler on the logger is removed before the new one is added."""
        hassette_logger = logging.getLogger("hassette")
        stale_q: queue.Queue[logging.LogRecord] = queue.Queue()
        stale_queue_handler = logging.handlers.QueueHandler(stale_q)
        hassette_logger.addHandler(stale_queue_handler)

        track_service(await make_initialized_logging_service())

        assert stale_queue_handler not in hassette_logger.handlers, (
            "Stale QueueHandler should have been removed by defensive cleanup"
        )
        # Exactly one QueueHandler: the new one
        queue_handlers = [h for h in hassette_logger.handlers if isinstance(h, logging.handlers.QueueHandler)]
        assert len(queue_handlers) == 1


class TestLoggingServiceOnShutdown:
    """LoggingService.on_shutdown stops the QueueListener and restores the stream handler."""

    async def test_on_shutdown_stops_listener_and_restores_stream_handler(self, track_service: TrackService) -> None:
        """Shutdown removes QueueHandler, re-adds StreamHandler, stops QueueListener."""
        hassette_logger = logging.getLogger("hassette")
        stream_handler = logging.StreamHandler()
        hassette_logger.addHandler(stream_handler)

        svc = track_service(await make_initialized_logging_service(stream_handler=stream_handler))
        # Record the pipeline objects that were installed — on_shutdown() clears both refs
        queue_handler = svc._queue_handler
        queue_listener = svc._queue_listener

        await svc.on_shutdown()

        # Stream handler restored
        assert stream_handler in hassette_logger.handlers
        # QueueHandler removed
        assert queue_handler not in hassette_logger.handlers
        # QueueListener stopped (thread should not be alive)
        assert queue_listener is not None
        # After stop(), the listener thread should exit — check its internal thread
        listener_thread = queue_listener._thread  # pyright: ignore[reportAttributeAccessIssue]
        if listener_thread is not None:
            assert not listener_thread.is_alive()

    async def test_on_shutdown_stops_listener_when_the_loops_fallback_bucket_is_sealed(
        self, track_service: TrackService
    ) -> None:
        """The QueueListener still stops at exit, after the root's TaskBucket (the loop's fallback) is sealed.

        Only fails without the fix on Python 3.11, where ``asyncio.wait_for`` wraps its awaitable in a task.
        """
        svc = track_service(await make_initialized_logging_service())
        queue_listener = svc._queue_listener
        assert queue_listener is not None

        with patch.object(queue_listener, "stop", wraps=queue_listener.stop) as stop, sealed_fallback_task_factory():
            await svc.on_shutdown()

        stop.assert_called_once()

    async def test_on_shutdown_sets_capture_handler_shutting_down(self, track_service: TrackService) -> None:
        """capture_handler.shutting_down is set to True during shutdown."""
        svc = track_service(await make_initialized_logging_service())
        assert not svc.capture_handler.shutting_down

        await svc.on_shutdown()
        assert svc.capture_handler.shutting_down

    async def test_on_shutdown_flushes_persistence_handler(self, track_service: TrackService) -> None:
        """flush_if_pending() is called on persistence_handler during shutdown."""
        svc = track_service(await make_initialized_logging_service())

        assert svc.persistence_handler is not None
        svc.persistence_handler.flush_if_pending = Mock()

        await svc.on_shutdown()

        svc.persistence_handler.flush_if_pending.assert_called_once()


class TestPyWarningsLoggerWiring:
    """py.warnings gets the same QueueHandler as hassette, so captured warnings (e.g.
    HassetteForgottenAwaitWarning) reach the full async pipeline — not just Phase 1's
    StreamHandler (issue #1816).
    """

    async def test_on_initialize_attaches_queue_handler_to_py_warnings_logger(
        self, track_service: TrackService
    ) -> None:
        """After init, py.warnings carries the same QueueHandler instance as hassette."""
        svc = track_service(await make_initialized_logging_service())

        warnings_logger = logging.getLogger("py.warnings")
        assert svc._queue_handler is not None
        assert svc._queue_handler in warnings_logger.handlers

    async def test_on_shutdown_restores_stream_handler_on_py_warnings_logger(self, track_service: TrackService) -> None:
        """Shutdown removes the QueueHandler and restores the StreamHandler on py.warnings too."""
        warnings_logger = logging.getLogger("py.warnings")
        stream_handler = logging.StreamHandler()
        warnings_logger.addHandler(stream_handler)

        svc = track_service(await make_initialized_logging_service(stream_handler=stream_handler))
        queue_handler = svc._queue_handler

        await svc.on_shutdown()

        assert stream_handler in warnings_logger.handlers
        assert queue_handler not in warnings_logger.handlers


class TestExtraLoggers:
    """A configured LoggingConfig.extra_loggers name is kept in sync through the Phase 1/2
    swap and Phase 2 teardown — see issue #1933.
    """

    def _extra_logger(self) -> logging.Logger:
        return logging.getLogger(EXTRA_LOGGER_NAME)

    async def test_on_initialize_attaches_queue_handler_to_extra_logger(self, track_service: TrackService) -> None:
        """After init, the extra logger carries the same QueueHandler instance as hassette."""
        svc = track_service(await make_logging_service_with_config(extra_loggers=[EXTRA_LOGGER_NAME]))

        extra_logger = self._extra_logger()
        assert svc._queue_handler is not None
        assert svc._queue_handler in extra_logger.handlers

    async def test_on_shutdown_restores_stream_handler_on_extra_logger(self, track_service: TrackService) -> None:
        """Shutdown removes the QueueHandler and restores the StreamHandler on the extra logger too."""
        extra_logger = self._extra_logger()
        stream_handler = logging.StreamHandler()
        extra_logger.addHandler(stream_handler)

        hassette = make_mock_hassette(sealed=False, logging={"extra_loggers": [EXTRA_LOGGER_NAME]})
        hassette.database_service = make_db_service()
        svc = track_service(await make_initialized_logging_service(hassette=hassette, stream_handler=stream_handler))
        queue_handler = svc._queue_handler

        await svc.on_shutdown()

        assert stream_handler in extra_logger.handlers
        assert queue_handler not in extra_logger.handlers

    async def test_no_extra_loggers_configured_leaves_other_loggers_untouched(
        self, track_service: TrackService
    ) -> None:
        """Without extra_loggers configured, only the standard LOGGER_NAMES get the QueueHandler."""
        svc = track_service(await make_initialized_logging_service())

        extra_logger = self._extra_logger()
        assert svc._queue_handler is not None
        assert svc._queue_handler not in extra_logger.handlers


class TestPersistenceActive:
    """persistence_active separates 'healthy, zero drops' from 'persistence unavailable'."""

    def test_false_before_initialize(self) -> None:
        """Before the pipeline starts there is no persistence."""
        svc = make_logging_service()

        assert svc.persistence_active is False

    async def test_true_after_initialize(self, track_service: TrackService) -> None:
        svc = track_service(await make_initialized_logging_service())

        assert svc.persistence_active is True

    async def test_false_when_persistence_handler_creation_fails(self, track_service: TrackService) -> None:
        """Pipeline runs but persistence is unavailable — DB write drops of 0 is not health."""
        hassette = make_mock_hassette(sealed=False)
        hassette.database_service = make_db_service()
        svc = track_service(make_logging_service(hassette=hassette))

        with patch(
            "hassette.core.logging_service.LogPersistenceHandler",
            side_effect=RuntimeError("db unavailable"),
        ):
            await svc.on_initialize()

        assert svc.db_write_queue_drops == 0
        assert svc.persistence_active is False

    async def test_false_after_shutdown(self, track_service: TrackService) -> None:
        svc = track_service(await make_initialized_logging_service())
        await svc.on_shutdown()

        assert svc.persistence_active is False


class TestDropCounters:
    """The two queue bottlenecks are counted separately."""

    async def test_both_counters_zero_when_no_persistence_handler(self, track_service: TrackService) -> None:
        hassette = make_mock_hassette(sealed=False)
        hassette.database_service = make_db_service()
        svc = track_service(make_logging_service(hassette=hassette))

        # With persistence_handler creation failing, the DB counter has nothing to read
        with patch(
            "hassette.core.logging_service.LogPersistenceHandler",
            side_effect=RuntimeError("unavailable"),
        ):
            await svc.on_initialize()

        assert svc.db_write_queue_drops == 0
        assert svc.log_queue_drops == 0

    async def test_db_write_queue_drops_reads_from_persistence_handler(self, track_service: TrackService) -> None:
        svc = track_service(await make_initialized_logging_service())

        assert svc.persistence_handler is not None
        # Manually bump the dropped counter via the lock
        with svc.persistence_handler._dropped_lock:
            svc.persistence_handler._dropped = 7

        assert svc.db_write_queue_drops == 7
        assert svc.log_queue_drops == 0

    async def test_db_write_queue_drops_survives_shutdown(self, track_service: TrackService) -> None:
        """The final count stays readable after the pipeline is torn down."""
        svc = track_service(await make_initialized_logging_service())

        assert svc.persistence_handler is not None
        with svc.persistence_handler._dropped_lock:
            svc.persistence_handler._dropped = 12

        await svc.on_shutdown()

        assert svc.db_write_queue_drops == 12

    async def test_log_queue_drops_survives_shutdown(self, track_service: TrackService) -> None:
        """The final log queue count stays readable after the pipeline is torn down."""
        svc = track_service(await make_initialized_logging_service())

        assert svc._queue_handler is not None
        with svc._queue_handler._dropped_lock:
            svc._queue_handler._dropped = 5

        await svc.on_shutdown()

        assert svc.log_queue_drops == 5

    async def test_log_queue_drops_reads_from_queue_handler(self, track_service: TrackService) -> None:
        """A full log queue is counted separately from DB write-queue drops."""
        hassette = make_mock_hassette(sealed=False)
        hassette.database_service = make_db_service()
        hassette.config.logging.log_queue_max = 1
        svc = track_service(make_logging_service(hassette=hassette))

        await svc.on_initialize()

        assert svc._queue_listener is not None
        # Stop the listener so nothing drains the queue, then overflow it.
        svc._queue_listener.stop()
        assert svc._queue_handler is not None
        for i in range(4):
            svc._queue_handler.emit(make_log_record(name="hassette", msg=f"m{i}"))

        assert svc.log_queue_drops > 0
        assert svc.db_write_queue_drops == 0

    async def test_log_queue_drops_zero_before_initialize(self) -> None:
        """No queue handler exists before on_initialize(), so the counter reads 0."""
        svc = make_logging_service()

        assert svc.log_queue_drops == 0


class TestSyncToAsyncSwap:
    """Verify no records are lost during the handler swap."""

    async def test_records_emitted_before_init_reach_capture_handler(self, track_service: TrackService) -> None:
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

        pre_capture = make_recording_log_capture_handler()
        hassette_logger.addHandler(stream_handler)
        hassette_logger.addHandler(pre_capture)

        svc = track_service(make_logging_service(stream_handler=stream_handler, hassette=hassette))
        svc.capture_handler = make_recording_log_capture_handler()

        n = 5
        for i in range(n):
            hassette_logger.warning("pre-init record %d", i)

        pre_init_msgs = [e for e in pre_capture.captured if e.message.startswith("pre-init record")]
        assert len(pre_init_msgs) == n

        await svc.on_initialize()

        m = 5
        for i in range(n, n + m):
            hassette_logger.warning("post-init record %d", i)

        await asyncio.sleep(0.1)

        post_init_msgs = [e.message for e in svc.capture_handler.captured if e.message.startswith("post-init record")]
        assert len(post_init_msgs) == m, (
            f"Expected {m} post-init records in capture handler, got {len(post_init_msgs)}: {post_init_msgs}"
        )
