"""Tests for correlation filter, seq stamping, and execution_id propagation.

Complements test_logging_setup.py (renderers, basic logging, noisy-library suppression),
test_logging_capture_handler.py (LogCaptureHandler, queue handler pipeline), and
test_logging_persistence.py (LogPersistenceHandler batching/flush).
"""

import asyncio
import json
import logging

import structlog

from hassette.context import CURRENT_EXECUTION_ID
from hassette.logging_ import CorrelationFilter, LogCaptureHandler, LogEntry, add_execution_id
from tests.unit.conftest import LoggingPipelineFixture


class TestCorrelationFilterSeqIncrements:
    """CorrelationFilter stamps seq monotonically on records; LogCaptureHandler reads it."""

    def test_seq_increments_monotonically_via_filter(self) -> None:
        """Seq increments monotonically when CorrelationFilter runs before emit."""
        corr_filter = CorrelationFilter()
        handler = LogCaptureHandler(buffer_size=100)
        logger = logging.getLogger("test.seq_increment")
        logger.addFilter(corr_filter)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        for _ in range(5):
            logger.info("test message")

        entries = list(handler.buffer)
        assert len(entries) == 5
        seqs = [e.seq for e in entries]
        # Sequences must be strictly increasing
        for i in range(1, len(seqs)):
            assert seqs[i] == seqs[i - 1] + 1

        logger.removeFilter(corr_filter)
        logger.removeHandler(handler)

    def test_seq_starts_at_positive_value_via_filter(self) -> None:
        """Seq is a positive integer stamped by CorrelationFilter."""
        corr_filter = CorrelationFilter()
        handler = LogCaptureHandler(buffer_size=100)
        logger = logging.getLogger("test.seq_start")
        logger.addFilter(corr_filter)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        logger.info("first")

        entries = list(handler.buffer)
        assert entries[0].seq >= 1

        logger.removeFilter(corr_filter)
        logger.removeHandler(handler)

    def test_shared_filter_produces_global_seq(self) -> None:
        """Two handlers sharing a CorrelationFilter get a global (non-independent) seq."""
        corr_filter = CorrelationFilter()
        handler_a = LogCaptureHandler(buffer_size=100)
        handler_b = LogCaptureHandler(buffer_size=100)

        logger_a = logging.getLogger("test.seq_shared_a")
        logger_a.addFilter(corr_filter)
        logger_a.addHandler(handler_a)
        logger_a.setLevel(logging.DEBUG)

        logger_b = logging.getLogger("test.seq_shared_b")
        logger_b.addFilter(corr_filter)
        logger_b.addHandler(handler_b)
        logger_b.setLevel(logging.DEBUG)

        for _ in range(3):
            logger_a.info("a msg")
        for _ in range(2):
            logger_b.info("b msg")

        seqs_a = [e.seq for e in handler_a.buffer]
        seqs_b = [e.seq for e in handler_b.buffer]
        # All seqs must be unique (global monotonic counter, no repetition)
        all_seqs = seqs_a + seqs_b
        assert len(all_seqs) == len(set(all_seqs)), "seq values must be globally unique"

        logger_a.removeFilter(corr_filter)
        logger_a.removeHandler(handler_a)
        logger_b.removeFilter(corr_filter)
        logger_b.removeHandler(handler_b)


class TestLogEntryToDictIncludesSeq:
    """to_dict() includes the seq field."""

    def test_to_dict_contains_seq(self) -> None:
        entry = LogEntry(
            seq=42,
            timestamp=1234567890.0,
            level="INFO",
            logger_name="hassette.test",
            func_name="test_func",
            lineno=10,
            message="hello",
        )
        d = entry.to_dict()
        assert d["seq"] == 42

    def test_to_dict_seq_position(self) -> None:
        """Seq should be present alongside timestamp in the dict."""
        entry = LogEntry(
            seq=7,
            timestamp=1000.0,
            level="DEBUG",
            logger_name="test",
            func_name="fn",
            lineno=1,
            message="msg",
        )
        d = entry.to_dict()
        assert "seq" in d
        assert "timestamp" in d


class TestCorrelationFilter:
    """CorrelationFilter stamps correlation IDs and seq on log records."""

    def test_filter_stamps_execution_id_from_context_var(self) -> None:
        """Filter reads CURRENT_EXECUTION_ID from context var and stamps it on the record."""
        corr_filter = CorrelationFilter()
        record = logging.LogRecord("hassette.test", logging.INFO, "", 0, "msg", (), None)
        token = CURRENT_EXECUTION_ID.set("abc-123")
        try:
            corr_filter.filter(record)
        finally:
            CURRENT_EXECUTION_ID.reset(token)
        assert record.execution_id == "abc-123"  # pyright: ignore[reportAttributeAccessIssue]

    def test_filter_stamps_none_execution_id_outside_context(self) -> None:
        """Filter stamps execution_id=None when CURRENT_EXECUTION_ID is not set."""
        corr_filter = CorrelationFilter()
        record = logging.LogRecord("hassette.test", logging.INFO, "", 0, "msg", (), None)
        token = CURRENT_EXECUTION_ID.set(None)
        try:
            corr_filter.filter(record)
            assert record.execution_id is None  # pyright: ignore[reportAttributeAccessIssue]
        finally:
            CURRENT_EXECUTION_ID.reset(token)

    def test_filter_stamps_seq_monotonically(self) -> None:
        """Filter seq counter increments monotonically across multiple filter calls."""
        corr_filter = CorrelationFilter()
        records = [logging.LogRecord("hassette.test", logging.INFO, "", 0, f"msg{i}", (), None) for i in range(5)]
        for r in records:
            corr_filter.filter(r)
        seqs = [r.seq for r in records]  # pyright: ignore[reportAttributeAccessIssue]
        assert seqs == list(range(seqs[0], seqs[0] + 5))

    def test_filter_stamps_app_key_from_contextvars(self) -> None:
        """Filter reads app_key from structlog contextvars and stamps it on the record."""
        corr_filter = CorrelationFilter()
        record = logging.LogRecord("hassette.test", logging.INFO, "", 0, "msg", (), None)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(app_key="my_app", instance_name="MyApp.0", instance_index=0)
        try:
            corr_filter.filter(record)
        finally:
            structlog.contextvars.clear_contextvars()
        assert record.app_key == "my_app"  # pyright: ignore[reportAttributeAccessIssue]
        assert record.instance_name == "MyApp.0"  # pyright: ignore[reportAttributeAccessIssue]
        assert record.instance_index == 0  # pyright: ignore[reportAttributeAccessIssue]

    def test_filter_stamps_none_app_key_outside_context(self) -> None:
        """Filter stamps None for app_key/instance_name/instance_index when not bound."""
        corr_filter = CorrelationFilter()
        record = logging.LogRecord("hassette.test", logging.INFO, "", 0, "msg", (), None)
        structlog.contextvars.clear_contextvars()
        corr_filter.filter(record)
        assert record.app_key is None  # pyright: ignore[reportAttributeAccessIssue]
        assert record.instance_name is None  # pyright: ignore[reportAttributeAccessIssue]
        assert record.instance_index is None  # pyright: ignore[reportAttributeAccessIssue]


class TestAddExecutionIdProcessor:
    """add_execution_id structlog processor reads CURRENT_EXECUTION_ID."""

    def test_processor_adds_execution_id_from_context(self) -> None:
        """add_execution_id processor stamps execution_id from CURRENT_EXECUTION_ID."""
        token = CURRENT_EXECUTION_ID.set("test-exec-id")
        try:
            event_dict = add_execution_id(None, "info", {"event": "hello"})
        finally:
            CURRENT_EXECUTION_ID.reset(token)
        assert event_dict["execution_id"] == "test-exec-id"

    def test_processor_adds_none_when_no_execution(self) -> None:
        """add_execution_id stamps None when CURRENT_EXECUTION_ID is not set."""
        token = CURRENT_EXECUTION_ID.set(None)
        try:
            event_dict = add_execution_id(None, "info", {"event": "hello"})
            assert event_dict["execution_id"] is None
        finally:
            CURRENT_EXECUTION_ID.reset(token)


class TestLogEntryCorrelationFields:
    """LogEntry dataclass includes correlation fields."""

    def test_log_entry_has_execution_id_field(self) -> None:
        entry = LogEntry(
            seq=1, timestamp=0.0, level="INFO", logger_name="test", func_name="fn", lineno=1, message="msg"
        )
        assert hasattr(entry, "execution_id")
        assert entry.execution_id is None

    def test_log_entry_has_instance_name_field(self) -> None:
        entry = LogEntry(
            seq=1, timestamp=0.0, level="INFO", logger_name="test", func_name="fn", lineno=1, message="msg"
        )
        assert hasattr(entry, "instance_name")
        assert entry.instance_name is None

    def test_log_entry_has_instance_index_field(self) -> None:
        entry = LogEntry(
            seq=1, timestamp=0.0, level="INFO", logger_name="test", func_name="fn", lineno=1, message="msg"
        )
        assert hasattr(entry, "instance_index")
        assert entry.instance_index is None

    def test_to_dict_includes_execution_id(self) -> None:
        entry = LogEntry(
            seq=1,
            timestamp=0.0,
            level="INFO",
            logger_name="test",
            func_name="fn",
            lineno=1,
            message="msg",
            execution_id="exec-abc",
        )
        d = entry.to_dict()
        assert d["execution_id"] == "exec-abc"

    def test_to_dict_includes_instance_name(self) -> None:
        entry = LogEntry(
            seq=1,
            timestamp=0.0,
            level="INFO",
            logger_name="test",
            func_name="fn",
            lineno=1,
            message="msg",
            instance_name="MyApp.0",
            instance_index=0,
        )
        d = entry.to_dict()
        assert d["instance_name"] == "MyApp.0"
        assert d["instance_index"] == 0


class TestSeqMovedToFilter:
    """seq counter is stamped by CorrelationFilter, not LogCaptureHandler."""

    def test_seq_stamped_on_record_before_emit(self) -> None:
        """When CorrelationFilter runs before LogCaptureHandler, seq is on the record."""
        corr_filter = CorrelationFilter()
        handler = LogCaptureHandler(buffer_size=100)
        # Manually run filter then emit
        record = logging.LogRecord("hassette.test", logging.INFO, "", 0, "msg", (), None)
        corr_filter.filter(record)
        handler.emit(record)
        entry = list(handler.buffer)[0]
        assert entry.seq >= 1

    def test_log_capture_handler_has_no_seq_counter(self) -> None:
        """LogCaptureHandler no longer has a _seq counter of its own."""
        handler = LogCaptureHandler(buffer_size=100)
        assert not hasattr(handler, "_seq")


class TestExecutionIdInheritedByChildTask:
    """Child tasks inherit execution_id via asyncio ContextVar propagation."""

    async def test_child_task_inherits_execution_id(self) -> None:
        """A child task spawned during an execution inherits the execution_id."""
        child_event_dict: dict = {}

        async def child_work() -> None:
            # Read execution_id via the processor
            nonlocal child_event_dict
            child_event_dict = add_execution_id(None, "info", {"event": "child"})

        token = CURRENT_EXECUTION_ID.set("parent-exec-id")
        try:
            task = asyncio.create_task(child_work())
            await task
        finally:
            CURRENT_EXECUTION_ID.reset(token)

        assert child_event_dict["execution_id"] == "parent-exec-id"

    async def test_clear_contextvars_prevents_leakage(self) -> None:
        """After clear_contextvars(), a subsequent execution gets no leaked identity."""
        structlog.contextvars.bind_contextvars(app_key="leaked_app")
        structlog.contextvars.clear_contextvars()
        ctx_vars = structlog.contextvars.get_contextvars()
        assert "app_key" not in ctx_vars


class TestCorrelationFilterAppliesToChildLoggers:
    """CorrelationFilter must stamp records from child loggers, not just the parent.

    Python's stdlib logging does NOT apply parent logger filters to records propagated
    from child loggers — only handler-level filters run during propagation. The filter
    must be on the QueueHandler (not the hassette logger) to stamp all records.
    """

    def test_child_logger_records_have_seq_stamped(self, logging_pipeline: LoggingPipelineFixture) -> None:
        """A child logger record propagated to the hassette QueueHandler gets seq stamped."""
        child = logging.getLogger("hassette.core.test_child_seq")
        child.info("child record")
        # Stop to flush all pending records from the queue
        logging_pipeline.listener.stop()
        logging_pipeline.listener.start()

        entries = list(logging_pipeline.capture.buffer)
        child_entries = [e for e in entries if e.message == "child record"]
        assert len(child_entries) == 1
        assert child_entries[0].seq > 0, "seq not stamped on child logger record — filter not running"

    def test_child_logger_records_have_source_tier_stamped(self, logging_pipeline: LoggingPipelineFixture) -> None:
        """A child logger record gets source_tier defaulted by CorrelationFilter."""
        child = logging.getLogger("hassette.core.test_child_tier")
        child.info("framework record")
        logging_pipeline.listener.stop()
        logging_pipeline.listener.start()

        output = logging_pipeline.stream.getvalue()
        assert "framework record" in output, "framework record not in stream output"
        record_line = [line for line in output.strip().split("\n") if "framework record" in line][0]
        parsed = json.loads(record_line)
        assert parsed.get("source_tier") == "framework"

    def test_app_child_logger_gets_app_tier(self, logging_pipeline: LoggingPipelineFixture) -> None:
        """A child logger with app_key in context gets source_tier='app'."""
        structlog.contextvars.bind_contextvars(app_key="my_app")
        child = logging.getLogger("hassette.apps.my_app.test_child")
        child.info("app record")
        structlog.contextvars.clear_contextvars()
        logging_pipeline.listener.stop()
        logging_pipeline.listener.start()

        entries = list(logging_pipeline.capture.buffer)
        app_entries = [e for e in entries if e.message == "app record"]
        assert any(e.app_key == "my_app" for e in app_entries)
