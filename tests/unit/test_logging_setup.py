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

import pytest

import hassette.logging_ as logging_module
from hassette.logging_ import enable_basic_logging
from tests.unit.conftest import LoggingPipelineFixture

# Fixture-only logger names used across TestExtraLoggers and TestExtraLoggerReconfiguration.
# Not real loggers anything else in the codebase writes to, but enable_basic_logging()'s
# snapshot/restore tracking (see logging_._extra_logger_snapshots) is process-global state —
# reset it and the loggers themselves after every test in this module so one test's
# extra_loggers config can never leak into another's assertions.
_TEST_EXTRA_LOGGER_NAMES = ("my_app.notify", "my_app.otf", "my_app.laundry")


@pytest.fixture(autouse=True)
def _reset_extra_logger_state():
    """Prevent this module's extra_loggers fixture names from leaking across tests.

    enable_basic_logging() restores a *real* extra logger to its pre-Hassette baseline once it
    drops out of a later call's extra_loggers list (see _restore_extra_logger) — but tests
    shouldn't rely on the implementation under test to isolate themselves. Reset directly.
    """
    yield
    for name in _TEST_EXTRA_LOGGER_NAMES:
        logging_module._extra_logger_snapshots.pop(name, None)
        logging_module._adopted_extra_loggers.discard(name)
        logger = logging.getLogger(name)
        logger.setLevel(logging.NOTSET)
        logger.propagate = True
        logger.disabled = False
        logger.handlers.clear()
        logger.filters.clear()


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


class TestCapturedWarningsRoutedToPipeline:
    """logging.captureWarnings(True) sends records to a 'py.warnings' logger — enable_basic_logging
    must wire that logger to the same handler as 'hassette', or captured warnings (e.g.
    HassetteForgottenAwaitWarning) reach a handler-less logger and are silently dropped (issue #1816).
    """

    def test_py_warnings_logger_configured_like_hassette_logger(self) -> None:
        """py.warnings gets the same stream handler, non-propagating, as the hassette logger."""
        stream = StringIO()
        handler = enable_basic_logging("WARNING", log_format="console", stream=stream)
        warnings_logger = logging.getLogger("py.warnings")
        assert warnings_logger.propagate is False
        assert handler in warnings_logger.handlers

    def test_captured_warning_reaches_console_stream(self) -> None:
        """A record on the 'py.warnings' logger — what logging.captureWarnings' internal
        _showwarning() emits — surfaces in the console stream, not just the message text.

        Exercises the 'py.warnings' logger directly rather than warnings.warn() itself:
        stdlib's captureWarnings() only rewires warnings.showwarning the first time it's
        toggled on per-process, and pytest's own per-test catch_warnings(record=True)
        wrapper installs a fresh recorder before every test body runs — so by the time
        this suite reaches this test, warnings.warn() no longer routes through hassette's
        _showwarning at all. That's a pytest/stdlib interaction, not something this fix
        touches; the handler wiring below is what issue #1816 actually changed.
        """
        stream = StringIO()
        enable_basic_logging("WARNING", log_format="console", stream=stream)

        logging.getLogger("py.warnings").warning("forgotten await test warning")

        output = stream.getvalue()
        assert "forgotten await test warning" in output


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


class TestExtraLoggers:
    """enable_basic_logging() attaches configured extra_loggers to the same pipeline as the
    hassette logger — see issue #1933.
    """

    def test_extra_logger_gets_same_handler_as_hassette_logger(self) -> None:
        """An extra logger name is attached to the same StreamHandler as 'hassette'."""
        stream = StringIO()
        handler = enable_basic_logging("INFO", log_format="console", stream=stream, extra_loggers=("my_app.notify",))
        extra_logger = logging.getLogger("my_app.notify")
        assert handler in extra_logger.handlers

    def test_extra_logger_gets_same_level_as_hassette_logger(self) -> None:
        """An extra logger is set to the configured log_level, not the root default."""
        stream = StringIO()
        enable_basic_logging("WARNING", log_format="console", stream=stream, extra_loggers=("my_app.notify",))
        extra_logger = logging.getLogger("my_app.notify")
        assert extra_logger.level == logging.WARNING

    def test_extra_logger_does_not_propagate(self) -> None:
        """An extra logger is set non-propagating, like the hassette logger."""
        stream = StringIO()
        enable_basic_logging("INFO", log_format="console", stream=stream, extra_loggers=("my_app.notify",))
        assert logging.getLogger("my_app.notify").propagate is False

    def test_extra_logger_record_reaches_stream(self) -> None:
        """A record logged on an extra logger name reaches the console stream."""
        stream = StringIO()
        enable_basic_logging("INFO", log_format="console", stream=stream, extra_loggers=("my_app.notify",))
        logging.getLogger("my_app.notify").info("extra logger message")
        assert "extra logger message" in stream.getvalue()

    def test_no_extra_loggers_by_default(self) -> None:
        """Omitting extra_loggers does not attach any additional logger names."""
        stream = StringIO()
        handler = enable_basic_logging("INFO", log_format="console", stream=stream)
        # No AttributeError, no unexpected loggers wired — a logger not passed as an
        # extra name keeps its own independent, unattached handler set.
        untouched_logger = logging.getLogger("some_unrelated_module")
        assert handler not in untouched_logger.handlers

    def test_multiple_extra_loggers_all_wired(self) -> None:
        """Multiple configured extra logger names are all attached."""
        stream = StringIO()
        handler = enable_basic_logging(
            "INFO",
            log_format="console",
            stream=stream,
            extra_loggers=("my_app.notify", "my_app.otf"),
        )
        assert handler in logging.getLogger("my_app.notify").handlers
        assert handler in logging.getLogger("my_app.otf").handlers

    def test_explicit_extra_logger_level_wins_over_noisy_suppression(self) -> None:
        """Opting a noisy-suppressed name into extra_loggers applies log_level, not the
        suppression default — the suppression block must run before this loop, not after.
        """
        stream = StringIO()
        enable_basic_logging("DEBUG", log_format="console", stream=stream, extra_loggers=("requests",))
        assert logging.getLogger("requests").level == logging.DEBUG

    def test_unconfigured_noisy_logger_still_suppressed(self) -> None:
        """A noisy-suppressed name not opted into extra_loggers keeps its WARNING default."""
        stream = StringIO()
        enable_basic_logging("DEBUG", log_format="console", stream=stream)
        assert logging.getLogger("requests").getEffectiveLevel() == logging.WARNING

    def test_adopting_a_disabled_logger_re_enables_it(self) -> None:
        """A logger previously disabled (e.g. by logging.config.dictConfig()'s default
        disable_existing_loggers=True) must be re-enabled on adoption — Logger.handle() no-ops
        entirely on a disabled logger regardless of level or attached handlers, so extra_loggers
        would otherwise silently do nothing for exactly this kind of pre-existing logger.
        """
        logging.getLogger("my_app.notify").disabled = True

        stream = StringIO()
        enable_basic_logging("INFO", log_format="console", stream=stream, extra_loggers=("my_app.notify",))

        assert logging.getLogger("my_app.notify").disabled is False


class TestExtraLoggerReconfiguration:
    """A second enable_basic_logging() call in the same process — a second Hassette()
    constructed with a different extra_loggers list — restores names dropped from the new
    list to their pre-Hassette state instead of leaving them attached to the old handler.
    """

    def test_dropped_extra_logger_is_detached_from_old_handler(self) -> None:
        first_stream = StringIO()
        first_handler = enable_basic_logging(
            "INFO", log_format="console", stream=first_stream, extra_loggers=("my_app.notify",)
        )
        assert first_handler in logging.getLogger("my_app.notify").handlers

        second_stream = StringIO()
        enable_basic_logging("INFO", log_format="console", stream=second_stream)

        assert first_handler not in logging.getLogger("my_app.notify").handlers

    def test_dropped_extra_logger_restores_exact_prior_state(self) -> None:
        """Restoration replays the logger's pre-Hassette level/propagate/disabled/handlers/
        filters exactly, not just a blank NOTSET/propagate=True/enabled/no-handlers reset.
        """
        original_handler = logging.StreamHandler(StringIO())
        original_filter = logging.Filter("original")
        pristine = logging.getLogger("my_app.laundry")
        pristine.setLevel(logging.ERROR)
        pristine.propagate = True
        pristine.disabled = True
        pristine.addHandler(original_handler)
        pristine.addFilter(original_filter)

        enable_basic_logging("INFO", log_format="console", stream=StringIO(), extra_loggers=("my_app.laundry",))
        enable_basic_logging("INFO", log_format="console", stream=StringIO())

        restored = logging.getLogger("my_app.laundry")
        assert restored.level == logging.ERROR
        assert restored.propagate is True
        assert restored.disabled is True
        assert restored.handlers == [original_handler]
        assert restored.filters == [original_filter]

    def test_still_configured_extra_logger_is_not_restored(self) -> None:
        """A name present in both calls' extra_loggers stays on the newest handler."""
        enable_basic_logging("INFO", log_format="console", stream=StringIO(), extra_loggers=("my_app.notify",))

        second_stream = StringIO()
        second_handler = enable_basic_logging(
            "WARNING", log_format="console", stream=second_stream, extra_loggers=("my_app.notify",)
        )

        extra_logger = logging.getLogger("my_app.notify")
        assert second_handler in extra_logger.handlers
        assert extra_logger.level == logging.WARNING

    def test_second_adopt_drop_cycle_restores_the_cycles_own_baseline(self) -> None:
        """A name adopted, dropped, reconfigured by its own owning code, then re-adopted and
        dropped again must restore to *that* reconfiguration — not the very first snapshot ever
        taken for this name. A stale, never-refreshed snapshot would silently discard whatever
        legitimate reconfiguration happened between the two adopt/drop cycles.
        """
        original_handler = logging.StreamHandler(StringIO())
        pristine = logging.getLogger("my_app.otf")
        pristine.setLevel(logging.ERROR)
        pristine.addHandler(original_handler)

        # Cycle 1: adopt, then drop — restores to the pristine state above.
        enable_basic_logging("INFO", log_format="console", stream=StringIO(), extra_loggers=("my_app.otf",))
        enable_basic_logging("INFO", log_format="console", stream=StringIO())
        assert logging.getLogger("my_app.otf").handlers == [original_handler]

        # The logger's owning code reconfigures it while it's not adopted by Hassette.
        reconfigured_handler = logging.StreamHandler(StringIO())
        owner_reconfigured = logging.getLogger("my_app.otf")
        owner_reconfigured.setLevel(logging.DEBUG)
        owner_reconfigured.handlers = [reconfigured_handler]

        # Cycle 2: adopt again, then drop again — must restore to the reconfiguration above,
        # not cycle 1's original snapshot.
        enable_basic_logging("INFO", log_format="console", stream=StringIO(), extra_loggers=("my_app.otf",))
        enable_basic_logging("INFO", log_format="console", stream=StringIO())

        restored = logging.getLogger("my_app.otf")
        assert restored.level == logging.DEBUG
        assert restored.handlers == [reconfigured_handler]


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
