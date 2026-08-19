"""Tests for structlog-based logging setup: renderers, basic logging, and noisy-library
suppression.

Complements test_logging_correlation.py (correlation filter, seq, execution_id),
test_logging_capture_handler.py (LogCaptureHandler, queue handler pipeline), and
test_logging_persistence.py (LogPersistenceHandler batching/flush).
"""

import inspect
import json
import logging
from io import StringIO
from unittest.mock import MagicMock

import hassette.logging_ as logging_module
from hassette.logging_ import enable_basic_logging
from tests.unit.conftest import LoggingPipelineFixture


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
