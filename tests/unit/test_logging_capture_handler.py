"""Tests for LogCaptureHandler, HassetteQueueHandler, and the queue handler pipeline.

Complements test_logging_setup.py (renderers, basic logging, noisy-library suppression),
test_logging_correlation.py (correlation filter, seq, execution_id), and
test_logging_persistence.py (LogPersistenceHandler batching/flush).
"""

import logging
import queue
from unittest.mock import MagicMock

from hassette.logging_ import HassetteQueueHandler, LogCaptureHandler
from hassette.web.models import LogWsMessage
from tests.unit.conftest import LoggingPipelineFixture


class TestLogCaptureHandlerStillCaptures:
    """LogCaptureHandler still captures records after structlog migration."""

    def test_capture_handler_captures_records(self, logging_pipeline: LoggingPipelineFixture) -> None:
        """LogCaptureHandler captures records via the pipeline."""
        initial_count = len(logging_pipeline.capture.buffer)
        child = logging.getLogger("hassette.test_capture")
        child.info("captured message")
        # Stop listener to flush all pending records
        logging_pipeline.listener.stop()
        logging_pipeline.listener.start()

        entries = list(logging_pipeline.capture.buffer)
        assert len(entries) == initial_count + 1
        assert entries[-1].message == "captured message"

    def test_capture_handler_reads_source_tier_from_record(self) -> None:
        """LogCaptureHandler reads source_tier from record attribute (not prefix-matching)."""
        handler = LogCaptureHandler(buffer_size=100)
        record = logging.LogRecord(
            name="hassette.apps.my_app",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test msg",
            args=(),
            exc_info=None,
        )
        record.source_tier = "app"
        handler.emit(record)

        entries = list(handler.buffer)
        assert len(entries) == 1
        assert entries[0].source_tier == "app"

    def test_capture_handler_source_tier_none_when_missing(self) -> None:
        """source_tier is None when record has no source_tier attribute."""
        handler = LogCaptureHandler(buffer_size=100)
        record = logging.LogRecord(
            name="hassette.core",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="framework msg",
            args=(),
            exc_info=None,
        )
        # No source_tier attribute set
        handler.emit(record)

        entries = list(handler.buffer)
        assert entries[0].source_tier is None

    def test_no_register_app_logger_method(self) -> None:
        """register_app_logger() is removed from LogCaptureHandler."""
        handler = LogCaptureHandler(buffer_size=100)
        assert not hasattr(handler, "register_app_logger")

    def test_no_resolve_app_key_method(self) -> None:
        """_resolve_app_key() is removed from LogCaptureHandler."""
        handler = LogCaptureHandler(buffer_size=100)
        assert not hasattr(handler, "_resolve_app_key")


class TestLogCaptureHandlerPopulatesCorrelationFields:
    """LogCaptureHandler.emit() populates correlation fields from record attributes."""

    def test_emit_reads_execution_id_from_record(self) -> None:
        handler = LogCaptureHandler(buffer_size=100)
        record = logging.LogRecord("hassette.test", logging.INFO, "", 0, "msg", (), None)
        record.execution_id = "exec-999"  # pyright: ignore[reportAttributeAccessIssue]
        handler.emit(record)
        entry = list(handler.buffer)[0]
        assert entry.execution_id == "exec-999"

    def test_emit_reads_instance_name_from_record(self) -> None:
        handler = LogCaptureHandler(buffer_size=100)
        record = logging.LogRecord("hassette.test", logging.INFO, "", 0, "msg", (), None)
        record.instance_name = "MyApp.0"  # pyright: ignore[reportAttributeAccessIssue]
        record.instance_index = 0  # pyright: ignore[reportAttributeAccessIssue]
        handler.emit(record)
        entry = list(handler.buffer)[0]
        assert entry.instance_name == "MyApp.0"
        assert entry.instance_index == 0

    def test_emit_execution_id_none_when_missing(self) -> None:
        handler = LogCaptureHandler(buffer_size=100)
        record = logging.LogRecord("hassette.test", logging.INFO, "", 0, "msg", (), None)
        handler.emit(record)
        entry = list(handler.buffer)[0]
        assert entry.execution_id is None


class TestQueueHandlerPipeline:
    """Records flow through the QueueHandler → QueueListener pipeline."""

    def test_hassette_logger_uses_queue_handler(self, logging_pipeline: LoggingPipelineFixture) -> None:
        """logging_pipeline installs a QueueHandler on the hassette logger.

        Note: other handlers may also be installed (e.g. by enable_basic_logging in
        other tests — we just verify a QueueHandler is present).
        """
        handler_types = [type(h).__name__ for h in logging_pipeline.logger.handlers]
        assert "QueueHandler" in handler_types

    def test_records_flow_through_stream_and_capture_handlers(self, logging_pipeline: LoggingPipelineFixture) -> None:
        """Records reach stream and capture handlers via the pipeline."""
        logging_pipeline.logger.setLevel(logging.INFO)
        child = logging.getLogger("hassette.test_all_handlers")
        child.info("pipeline test")
        logging_pipeline.listener.stop()

        assert "pipeline test" in logging_pipeline.stream.getvalue()

        entries = list(logging_pipeline.capture.buffer)
        assert any(e.message == "pipeline test" for e in entries)

        logging_pipeline.listener.start()

    def test_shutdown_flushes_all_pending_records(self, logging_pipeline: LoggingPipelineFixture) -> None:
        """After stopping the listener, all enqueued records appear in handler output."""
        logging_pipeline.logger.setLevel(logging.INFO)
        child = logging.getLogger("hassette.test_shutdown_flush")
        for i in range(20):
            child.info("record_%d", i)
        logging_pipeline.listener.stop()

        output = logging_pipeline.stream.getvalue()
        for i in range(20):
            assert f"record_{i}" in output, f"record_{i} missing from output after listener stop"

        logging_pipeline.listener.start()


class TestHassetteQueueHandlerDrops:
    """HassetteQueueHandler counts records the bounded log queue could not accept."""

    def test_records_enqueue_without_dropping_when_space_remains(self) -> None:
        """A record that fits in the queue is enqueued and not counted as dropped."""
        q: queue.Queue[logging.LogRecord] = queue.Queue(maxsize=2)
        handler = HassetteQueueHandler(q)

        handler.emit(logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None))

        assert handler.log_queue_drops == 0
        assert q.qsize() == 1

    def test_counts_drops_when_queue_is_full(self) -> None:
        """Records emitted against a full queue increment log_queue_drops instead of raising."""
        q: queue.Queue[logging.LogRecord] = queue.Queue(maxsize=2)
        handler = HassetteQueueHandler(q)

        for i in range(5):
            handler.emit(logging.LogRecord("test", logging.INFO, "", 0, f"msg{i}", (), None))

        assert q.qsize() == 2
        assert handler.log_queue_drops == 3

    def test_drop_does_not_reach_handle_error(self) -> None:
        """A full queue is a counted drop, not a handler error written to stderr."""
        q: queue.Queue[logging.LogRecord] = queue.Queue(maxsize=1)
        handler = HassetteQueueHandler(q)
        errors: list[logging.LogRecord] = []
        handler.handleError = errors.append  # pyright: ignore[reportAttributeAccessIssue]

        for i in range(3):
            handler.emit(logging.LogRecord("test", logging.INFO, "", 0, f"msg{i}", (), None))

        assert errors == []
        assert handler.log_queue_drops == 2


class TestLogCaptureHandlerShutdownGuard:
    """LogCaptureHandler.shutting_down prevents broadcast during shutdown."""

    def test_shutting_down_skips_broadcast(self) -> None:
        """When shutting_down is True, emit() still captures but skips call_soon_threadsafe."""
        handler = LogCaptureHandler(buffer_size=100)
        loop = MagicMock()
        loop.is_running.return_value = True
        broadcast_fn = MagicMock()
        handler.set_broadcast(broadcast_fn, loop)

        handler.shutting_down = True
        record = logging.LogRecord("test", logging.INFO, "", 0, "shutdown msg", (), None)
        handler.emit(record)

        entries = list(handler.buffer)
        assert len(entries) == 1
        assert entries[0].message == "shutdown msg"
        loop.call_soon_threadsafe.assert_not_called()

    def test_not_shutting_down_broadcasts(self) -> None:
        """When shutting_down is False, emit() broadcasts via call_soon_threadsafe."""
        handler = LogCaptureHandler(buffer_size=100)
        loop = MagicMock()
        loop.is_running.return_value = True
        broadcast_fn = MagicMock()
        handler.set_broadcast(broadcast_fn, loop)

        record = logging.LogRecord("test", logging.INFO, "", 0, "live msg", (), None)
        handler.emit(record)

        loop.call_soon_threadsafe.assert_called_once()


def emit_and_capture_broadcast(handler: LogCaptureHandler, loop: MagicMock, broadcast_fn: MagicMock) -> dict:
    """Emit one record and return the envelope dict passed to the broadcast fn.

    emit() schedules a closure via call_soon_threadsafe; this runs it so broadcast_fn(payload) fires.
    """
    record = logging.LogRecord("hassette.test", logging.INFO, "", 0, "live msg", (), None)
    handler.emit(record)

    scheduled = loop.call_soon_threadsafe.call_args.args[0]
    scheduled()

    broadcast_fn.assert_called_once()
    return broadcast_fn.call_args.args[0]


class TestLogCaptureHandlerBroadcastEnvelope:
    """The live log broadcast envelope matches the LogWsMessage schema the frontend validates against."""

    def test_broadcast_envelope_includes_top_level_timestamp(self) -> None:
        """The envelope carries a top-level 'timestamp' — without it the frontend drops the message."""
        handler = LogCaptureHandler(buffer_size=100)
        loop = MagicMock()
        loop.is_running.return_value = True
        broadcast_fn = MagicMock()
        handler.set_broadcast(broadcast_fn, loop)

        payload = emit_and_capture_broadcast(handler, loop, broadcast_fn)

        assert payload["type"] == "log"
        assert "timestamp" in payload, "log WS envelope missing top-level timestamp"
        assert isinstance(payload["timestamp"], float)

    def test_broadcast_envelope_validates_against_log_ws_message(self) -> None:
        """The envelope round-trips through LogWsMessage, the model the frontend schema is generated from."""
        handler = LogCaptureHandler(buffer_size=100)
        loop = MagicMock()
        loop.is_running.return_value = True
        broadcast_fn = MagicMock()
        handler.set_broadcast(broadcast_fn, loop)

        payload = emit_and_capture_broadcast(handler, loop, broadcast_fn)

        LogWsMessage.model_validate(payload)
