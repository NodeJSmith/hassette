"""Tests for structlog-based logging infrastructure."""

import asyncio
import inspect
import json
import logging
import queue
import time
from io import StringIO
from unittest.mock import MagicMock

import structlog

import hassette.logging_ as logging_module
from hassette.context import CURRENT_EXECUTION_ID
from hassette.logging_ import (
    CorrelationFilter,
    HassetteQueueListener,
    LogCaptureHandler,
    LogEntry,
    LogPersistenceHandler,
    add_execution_id,
    enable_basic_logging,
)
from hassette.web.models import LogWsMessage
from tests.unit.conftest import LoggingPipelineFixture


class TestCorrelationFilterSeqIncrements:
    """CorrelationFilter stamps seq monotonically on records; LogCaptureHandler reads it."""

    def test_seq_increments_monotonically_via_filter(self) -> None:
        """seq increments monotonically when CorrelationFilter runs before emit."""
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
        """seq is a positive integer stamped by CorrelationFilter."""
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
        """seq should be present alongside timestamp in the dict."""
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


class TestLoggingPipelineConsoleRenderer:
    """ConsoleRenderer is used when log_format='console' via enable_basic_logging."""

    def test_console_renderer_output(self) -> None:
        """enable_basic_logging outputs human-readable format when configured for console."""
        stream = StringIO()
        enable_basic_logging("INFO", log_format="console", stream=stream)
        logger = logging.getLogger("hassette.test_console")
        logger.info("hello console")
        output = stream.getvalue()
        assert "hello console" in output
        assert "{" not in output or '"event"' not in output

    def test_hassette_logger_level_set(self) -> None:
        """enable_basic_logging applies the requested log level."""
        stream = StringIO()
        enable_basic_logging("WARNING", log_format="console", stream=stream)
        logger = logging.getLogger("hassette")
        assert logger.level == logging.WARNING


class TestLoggingPipelineJSONRenderer:
    """JSONRenderer is used by the logging_pipeline fixture."""

    def test_json_renderer_used(self, logging_pipeline: LoggingPipelineFixture) -> None:
        """Records written to the pipeline appear as JSON in the stream."""
        child = logging.getLogger("hassette.test_json")
        child.info("hello json")
        logging_pipeline.listener.stop()

        output = logging_pipeline.stream.getvalue()
        lines = [line for line in output.strip().splitlines() if line.strip()]
        assert len(lines) >= 1
        parsed = json.loads(lines[-1])
        assert parsed["event"] == "hello json"

        logging_pipeline.listener.start()

    def test_json_output_has_level_field(self, logging_pipeline: LoggingPipelineFixture) -> None:
        """JSON output includes a 'level' field."""
        stream = StringIO()
        enable_basic_logging("INFO", log_format="json", stream=stream)
        logger = logging.getLogger("hassette.test_json_level")
        logger.warning("level test")
        output = stream.getvalue()
        lines = [line for line in output.strip().splitlines() if line.strip()]
        parsed = json.loads(lines[-1])
        assert parsed["level"] == "warning"

    def test_source_tier_appears_in_json_output_via_record_filter(self) -> None:
        """source_tier appears in JSON output when stamped by a filter."""
        stream = StringIO()
        enable_basic_logging("INFO", log_format="json", stream=stream)
        logger = logging.getLogger("hassette.test_source_tier_json")
        logger.addFilter(
            type("F", (logging.Filter,), {"filter": lambda _self, r: setattr(r, "source_tier", "app") or True})()
        )
        logger.info("tier test")
        output = stream.getvalue()
        lines = [line for line in output.strip().splitlines() if line.strip()]
        parsed = json.loads(lines[-1])
        assert parsed.get("source_tier") == "app"


class TestEnableBasicLoggingAutoFormat:
    """TTY detection when log_format='auto'."""

    def test_auto_uses_console_renderer_when_tty(self) -> None:
        stream = MagicMock(spec=StringIO)
        stream.isatty = MagicMock(return_value=True)
        stream.write = MagicMock()
        stream.flush = MagicMock()
        # Should not raise; just verify it calls isatty
        enable_basic_logging("INFO", log_format="auto", stream=stream)
        stream.isatty.assert_called()

    def test_auto_uses_json_renderer_when_not_tty(self) -> None:
        stream = StringIO()
        enable_basic_logging("INFO", log_format="auto", stream=stream)
        logger = logging.getLogger("hassette.test_auto_notty")
        logger.info("auto json")
        output = stream.getvalue()
        lines = [line for line in output.strip().splitlines() if line.strip()]
        assert len(lines) >= 1
        parsed = json.loads(lines[-1])
        assert parsed["event"] == "auto json"


class TestNoisyLibrarySuppression:
    """Noisy library suppression still works after structlog migration."""

    def test_requests_logger_at_warning(self) -> None:
        stream = StringIO()
        enable_basic_logging("INFO", log_format="console", stream=stream)
        assert logging.getLogger("requests").getEffectiveLevel() == logging.WARNING

    def test_urllib3_logger_at_warning(self) -> None:
        stream = StringIO()
        enable_basic_logging("INFO", log_format="console", stream=stream)
        assert logging.getLogger("urllib3").getEffectiveLevel() == logging.WARNING

    def test_aiohttp_access_logger_at_warning(self) -> None:
        stream = StringIO()
        enable_basic_logging("INFO", log_format="console", stream=stream)
        assert logging.getLogger("aiohttp.access").getEffectiveLevel() == logging.WARNING

    def test_httpx_logger_at_warning(self) -> None:
        stream = StringIO()
        enable_basic_logging("INFO", log_format="console", stream=stream)
        assert logging.getLogger("httpx2").getEffectiveLevel() == logging.WARNING


class TestLogCaptureHandlerStillCaptures:
    """LogCaptureHandler still captures records after structlog migration."""

    def test_capture_handler_captures_records(self, logging_pipeline: LoggingPipelineFixture) -> None:
        """LogCaptureHandler captures records via the pipeline."""
        initial_count = len(logging_pipeline.capture.get_buffer_snapshot())
        child = logging.getLogger("hassette.test_capture")
        child.info("captured message")
        # Stop listener to flush all pending records
        logging_pipeline.listener.stop()
        logging_pipeline.listener.start()

        entries = logging_pipeline.capture.get_buffer_snapshot()
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


class TestColoredlogsRemoved:
    """coloredlogs is not imported anywhere in the codebase."""

    def test_coloredlogs_not_imported_in_logging_module(self) -> None:
        # coloredlogs should not be importable via logging_ module
        assert not hasattr(logging_module, "coloredlogs")

    def test_enable_basic_logging_has_log_format_parameter(self) -> None:
        """enable_basic_logging() signature includes log_format parameter."""
        sig = inspect.signature(enable_basic_logging)
        assert "log_format" in sig.parameters


class TestEnableBasicLogging:
    """enable_basic_logging() sets up synchronous console logging and returns the StreamHandler."""

    def test_returns_stream_handler(self) -> None:
        """enable_basic_logging() returns a logging.StreamHandler instance."""
        stream = StringIO()
        result = enable_basic_logging("INFO", log_format="console", stream=stream)
        assert isinstance(result, logging.StreamHandler)

    def test_stream_handler_attached_to_hassette_logger(self) -> None:
        """The returned StreamHandler is attached directly to the hassette logger."""
        stream = StringIO()
        handler = enable_basic_logging("INFO", log_format="console", stream=stream)
        logger = logging.getLogger("hassette")
        assert handler in logger.handlers

    def test_no_queue_handler_installed(self) -> None:
        """enable_basic_logging() does NOT install a QueueHandler — synchronous only."""
        stream = StringIO()
        enable_basic_logging("INFO", log_format="console", stream=stream)
        logger = logging.getLogger("hassette")
        handler_types = [type(h).__name__ for h in logger.handlers]
        assert "QueueHandler" not in handler_types

    def test_log_output_is_synchronous(self) -> None:
        """Records written after enable_basic_logging() appear in the stream immediately."""
        stream = StringIO()
        enable_basic_logging("INFO", log_format="console", stream=stream)
        logger = logging.getLogger("hassette.test_basic_sync")
        logger.info("synchronous message")
        output = stream.getvalue()
        assert "synchronous message" in output

    def test_log_level_applied(self) -> None:
        """The hassette logger level is set to the requested level."""
        stream = StringIO()
        enable_basic_logging("WARNING", log_format="console", stream=stream)
        assert logging.getLogger("hassette").level == logging.WARNING

    def test_propagate_false(self) -> None:
        """enable_basic_logging() sets propagate=False on the hassette logger."""
        stream = StringIO()
        enable_basic_logging("INFO", log_format="console", stream=stream)
        assert logging.getLogger("hassette").propagate is False

    def test_noisy_libraries_suppressed(self) -> None:
        """enable_basic_logging() suppresses noisy library loggers."""
        stream = StringIO()
        enable_basic_logging("INFO", log_format="console", stream=stream)
        assert logging.getLogger("requests").getEffectiveLevel() == logging.WARNING
        assert logging.getLogger("urllib3").getEffectiveLevel() == logging.WARNING
        assert logging.getLogger("aiohttp.access").getEffectiveLevel() == logging.WARNING
        assert logging.getLogger("httpx2").getEffectiveLevel() == logging.WARNING

    def test_json_format_selected(self) -> None:
        """enable_basic_logging() supports log_format='json'."""
        stream = StringIO()
        enable_basic_logging("INFO", log_format="json", stream=stream)
        logger = logging.getLogger("hassette.test_basic_json")
        logger.info("json basic test")
        output = stream.getvalue()
        lines = [line for line in output.strip().splitlines() if line.strip()]
        assert len(lines) >= 1
        parsed = json.loads(lines[-1])
        assert parsed["event"] == "json basic test"

    def test_returned_handler_uses_correct_stream(self) -> None:
        """The returned StreamHandler's stream matches what was passed."""
        stream = StringIO()
        handler = enable_basic_logging("INFO", log_format="console", stream=stream)
        assert handler.stream is stream


class TestNoModuleGlobals:
    """Module-level globals and accessor functions are removed."""

    def test_no_get_log_capture_handler(self) -> None:
        """get_log_capture_handler() is removed from logging_ module."""
        assert not hasattr(logging_module, "get_log_capture_handler")

    def test_no_get_log_persistence_handler(self) -> None:
        """get_log_persistence_handler() is removed from logging_ module."""
        assert not hasattr(logging_module, "get_log_persistence_handler")

    def test_no_shutdown_logging(self) -> None:
        """shutdown_logging() is removed from logging_ module."""
        assert not hasattr(logging_module, "shutdown_logging")

    def test_no_enable_logging(self) -> None:
        """enable_logging() is removed from logging_ module."""
        assert not hasattr(logging_module, "enable_logging")

    def test_no_module_capture_handler_global(self) -> None:
        """_log_capture_handler module global is removed."""
        assert not hasattr(logging_module, "_log_capture_handler")

    def test_no_module_persistence_handler_global(self) -> None:
        """_log_persistence_handler module global is removed."""
        assert not hasattr(logging_module, "_log_persistence_handler")

    def test_no_queue_listener_global(self) -> None:
        """_queue_listener module global is removed."""
        assert not hasattr(logging_module, "_queue_listener")


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

        entries = logging_pipeline.capture.get_buffer_snapshot()
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

        entries = logging_pipeline.capture.get_buffer_snapshot()
        app_entries = [e for e in entries if e.message == "app record"]
        assert any(e.app_key == "my_app" for e in app_entries)


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

        entries = logging_pipeline.capture.get_buffer_snapshot()
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


def _make_dropping_db_service() -> MagicMock:
    """Return a db_service mock whose enqueue() always returns False (simulates full queue)."""
    db_service = MagicMock()
    db_service._insert_log_records = MagicMock(return_value=MagicMock())

    def drop_enqueue(coro):
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
            assert handler.dropped_count == 50
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

            assert handler.dropped_count == 0
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
            assert handler.dropped_count == 10
            assert len(handler._batch) == 0
        finally:
            loop.close()

    def test_drops_records_on_queue_full(self) -> None:
        """Records are counted as dropped when enqueue() returns False (queue full)."""
        loop = asyncio.new_event_loop()
        db_service = _make_dropping_db_service()
        handler = LogPersistenceHandler(db_service, loop, persistence_level=logging.DEBUG)
        try:
            assert handler.dropped_count == 0

            for i in range(100):
                record = logging.LogRecord("test", logging.INFO, "", 0, f"msg{i}", (), None)
                handler.emit(record)

            handler.flush_if_pending()
            loop.run_until_complete(asyncio.sleep(0))
            assert handler.dropped_count == 100
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
            assert handler.dropped_count == 0
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
            assert handler.dropped_count == 5
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

        assert handler.dropped_count == 3
        assert len(handler._batch) == 0


class TestLogPersistenceDropCountWithDB:
    """LogPersistenceHandler counts drops caused by DB queue-full backpressure."""

    @staticmethod
    def enqueue_returning_false(coro):
        coro.close()
        return False

    @staticmethod
    def enqueue_raising_runtime_error(coro):
        coro.close()
        raise RuntimeError("DB shut down")

    def test_dropped_count_increments_on_enqueue_failure(self) -> None:
        """When enqueue() returns False (queue full), dropped_count increases."""
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

            assert handler.dropped_count == 50
        finally:
            loop.close()

    def test_dropped_count_increments_on_db_shutdown_runtime_error(self) -> None:
        """When enqueue() raises RuntimeError (DB shut down), dropped_count increases."""
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

            assert handler.dropped_count == 50
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
        assert persistence.dropped_count == 1
        assert len(persistence._batch) == 0


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
