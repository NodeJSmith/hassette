"""Tests for structlog-based logging setup: renderers, basic logging, and noisy-library
suppression.

Complements test_logging_correlation.py (correlation filter, seq, execution_id),
test_logging_capture_handler.py (LogCaptureHandler, queue handler pipeline), and
test_logging_persistence.py (LogPersistenceHandler batching/flush).
"""

import inspect
import json
import logging
import queue
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from io import StringIO
from typing import Any, Literal
from unittest.mock import MagicMock

import pytest
import structlog

import hassette.logging_ as logging_module
from hassette.const import HASSETTE_LOGGER_NAME
from hassette.context import CURRENT_EXECUTION_ID
from hassette.logging_ import (
    CorrelationFilter,
    HassetteQueueHandler,
    HassetteQueueListener,
    LogFormat,
    LogIdentity,
    LogIdentityFilter,
    LogPersistenceHandler,
    enable_basic_logging,
    set_logger_identity,
)
from hassette.logging_processors import console_identity, identity_label
from tests.support.helpers import last_json_record
from tests.unit.conftest import LoggingPipelineFixture

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")
STDLIB_LOGGER_NAME = "hassette.apps.example_stdlib"
NATIVE_LOGGER_NAME = "hassette.apps.example_native"
# A UUIDv7 execution id and the short id the console shows for it.
EXECUTION_ID = "0192f3a1-7c2e-7b44-9d0f-6e1a41c09e7b"
SHORT_EXECUTION_ID = "@41c09e7b"

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

        parsed = last_json_record(logging_pipeline.stream)
        assert parsed["event"] == "hello json"

        logging_pipeline.listener.start()

    def test_json_output_has_level_field(self, logging_pipeline: LoggingPipelineFixture) -> None:
        """JSON output includes a 'level' field."""
        stream = StringIO()
        enable_basic_logging("INFO", log_format="json", stream=stream)
        logger = logging.getLogger("hassette.test_json_level")
        logger.warning("level test")
        assert last_json_record(stream)["level"] == "warning"

    def test_author_appears_in_json_output_from_logger_identity(self) -> None:
        """The author fixed on the writing logger appears as author in JSON output."""
        stream = StringIO()
        enable_basic_logging("INFO", log_format="json", stream=stream)
        logger = logging.getLogger("hassette.test_author_json")
        set_logger_identity(logger, LogIdentity(author="app"))
        logger.info("author test")
        assert last_json_record(stream).get("author") == "app"


class TestEnableBasicLoggingAutoFormat:
    """TTY detection when log_format='auto'."""

    def test_auto_uses_console_renderer_when_tty(self) -> None:
        stream = MagicMock(spec=StringIO)
        stream.isatty = MagicMock(return_value=True)
        enable_basic_logging("INFO", log_format="auto", stream=stream)
        assert isinstance(_installed_renderer(), structlog.dev.ConsoleRenderer)

    def test_auto_uses_json_renderer_when_not_tty(self) -> None:
        stream = StringIO()
        enable_basic_logging("INFO", log_format="auto", stream=stream)
        assert isinstance(_installed_renderer(), structlog.processors.JSONRenderer)
        logger = logging.getLogger("hassette.test_auto_notty")
        logger.info("auto json")
        assert last_json_record(stream)["event"] == "auto json"


class TestIdentityLabel:
    """identity_label: subject or logger, framework marker, short execution id."""

    def test_app_line_shows_subject(self) -> None:
        event = {"logger": "hassette.apps.garage_door", "author": "app", "instance_name": "garage_door"}
        assert identity_label(event) == "garage_door"

    def test_framework_line_about_app_is_marked(self) -> None:
        event = {"logger": "hassette.core.bus_service", "author": "framework", "instance_name": "garage_door"}
        assert identity_label(event) == "hassette:garage_door"

    @pytest.mark.parametrize(
        ("logger_name", "expected"),
        [
            ("hassette.core.websocket_service", "core.websocket_service"),
            ("hassette.apps.garage_door", "apps.garage_door"),
            ("hassette", "hassette"),
            ("uvicorn.error", "uvicorn.error"),
        ],
    )
    def test_ownerless_line_shows_logger_without_hassette_prefix(self, logger_name: str, expected: str) -> None:
        assert identity_label({"logger": logger_name, "author": "framework"}) == expected

    def test_execution_id_shows_random_tail(self) -> None:
        """UUIDv7 ids share their leading timestamp characters, so the short id is the tail."""
        event = {
            "logger": "hassette.core.bus_service",
            "author": "framework",
            "instance_name": "garage_door",
            "execution_id": EXECUTION_ID,
        }
        assert identity_label(event) == f"hassette:garage_door {SHORT_EXECUTION_ID}"

    def test_no_logger_and_no_subject_is_empty(self) -> None:
        assert identity_label({}) == ""


class TestConsoleIdentityProcessor:
    """console_identity keeps only what a console line renders."""

    def test_drops_every_other_key(self) -> None:
        event = {
            "timestamp": "2026-10-22T14:44:54.728999",
            "level": "info",
            "event": "hello",
            "logger": "hassette.apps.garage_door",
            "author": "app",
            "app_key": "garage",
            "instance_name": "garage_door",
            "instance_index": 0,
            "listener_id": 7,
        }
        assert console_identity(None, "info", event) == {
            "timestamp": "2026-10-22T14:44:54.728999",
            "level": "info",
            "event": "hello",
            "identity": "garage_door",
        }

    def test_keeps_exception_keys(self) -> None:
        event = {"event": "boom", "logger": "hassette", "exc_info": True, "stack": "s"}
        out = console_identity(None, "error", event)
        assert out["exc_info"] is True
        assert out["stack"] == "s"

    def test_does_not_mutate_input(self) -> None:
        event = {"event": "hello", "logger": "hassette.core", "app_key": "garage"}
        console_identity(None, "info", event)
        assert event == {"event": "hello", "logger": "hassette.core", "app_key": "garage"}


class TestConsoleLineFormat:
    """Rendered console and compact lines: identity column before the message, no key=value tail."""

    @pytest.fixture
    def app_logger(self) -> logging.Logger:
        logger = logging.getLogger("hassette.apps.example_app")
        set_logger_identity(
            logger, LogIdentity(author="app", app_key="example", instance_name="example_app", instance_index=0)
        )
        return logger

    def render(self, log_format: Literal["console", "compact"], emit: Callable[[], None]) -> str:
        """Log one line through a fresh enable_basic_logging handler and return it without ANSI codes."""
        stream = StringIO()
        enable_basic_logging("INFO", log_format=log_format, stream=stream)
        emit()
        return ANSI_ESCAPE.sub("", stream.getvalue()).rstrip("\n")

    def test_compact_app_line(self, app_logger: logging.Logger) -> None:
        line = self.render("compact", lambda: app_logger.info("hello"))
        assert re.fullmatch(r"\d{2}:\d{2}:\d{2} \[info\] \[example_app\] hello", line), line

    def test_console_line_has_no_tail(self, app_logger: logging.Logger) -> None:
        line = self.render("console", lambda: app_logger.info("hello"))
        assert re.fullmatch(r"\S+ \[info +\] \[example_app\] hello", line), line

    def test_framework_line_about_app_inside_execution(self) -> None:
        def emit() -> None:
            with execution_scope(EXECUTION_ID, instance_name="garage_door"):
                logging.getLogger("hassette.core.test_executor").error("Handler failed")

        line = self.render("compact", emit)
        assert line.endswith(f"[error] [hassette:garage_door {SHORT_EXECUTION_ID}] Handler failed"), line

    def test_ownerless_framework_line_shows_logger(self) -> None:
        line = self.render("compact", lambda: logging.getLogger("hassette.core.test_ws").info("Connected"))
        assert line.endswith("[info] [core.test_ws] Connected"), line

    @pytest.mark.parametrize("log_format", ["console", "compact"])
    def test_stdlib_stack_info_is_rendered(
        self, app_logger: logging.Logger, log_format: Literal["console", "compact"]
    ) -> None:
        output = self.render(log_format, lambda: app_logger.info("where am I", stack_info=True))
        assert "Stack (most recent call last):" in output, output
        assert "test_stdlib_stack_info_is_rendered" in output, output

    @pytest.mark.parametrize("log_format", ["console", "compact"])
    def test_structlog_stack_info_is_rendered(self, log_format: Literal["console", "compact"]) -> None:
        native = structlog.get_logger("hassette.apps.example_native")
        output = self.render(log_format, lambda: native.info("where am I", stack_info=True))
        assert "Stack (most recent call last):" in output, output
        assert "test_structlog_stack_info_is_rendered" in output, output


@contextmanager
def queued_pipeline(*handlers: logging.Handler) -> Iterator[None]:
    """Route the hassette logger through a queue to ``handlers``, as ``LoggingService`` does in Phase 2.

    The first handler is the ``enable_basic_logging`` stream handler that the queue replaces.
    """
    logger = logging.getLogger(HASSETTE_LOGGER_NAME)
    log_queue: queue.Queue[logging.LogRecord] = queue.Queue()
    queue_handler = HassetteQueueHandler(log_queue)
    queue_handler.addFilter(LogIdentityFilter())
    queue_handler.addFilter(CorrelationFilter())
    listener = HassetteQueueListener(log_queue, *handlers)
    logger.addHandler(queue_handler)
    logger.removeHandler(handlers[0])
    listener.start()
    try:
        yield
    finally:
        listener.stop()
        logger.removeHandler(queue_handler)
        logger.addHandler(handlers[0])


def log_caught_error(logger: Any, *, via_exc_info: bool = False) -> None:
    """Log ``"failed"`` while a ``ValueError("kaboom")`` is being handled.

    ``via_exc_info`` logs with ``error(..., exc_info=True)`` instead of ``exception()``.
    """
    try:
        raise ValueError("kaboom")
    except ValueError:
        if via_exc_info:
            logger.error("failed", exc_info=True)  # noqa: G201 - the exc_info=True path is under test
        else:
            logger.exception("failed")


def render(log_format: LogFormat, emit: Callable[[], None], *, queued: bool) -> str:
    """Log through a fresh ``enable_basic_logging`` handler, optionally behind the Phase 2 queue."""
    stream = StringIO()
    stream_handler = enable_basic_logging("INFO", log_format=log_format, stream=stream)
    if queued:
        with queued_pipeline(stream_handler):
            emit()
    else:
        emit()
    return ANSI_ESCAPE.sub("", stream.getvalue())


@pytest.mark.parametrize("queued", [False, True], ids=["sync", "queued"])
class TestJsonStackAndException:
    """JSON output carries stdlib and structlog-native callers' stacks under ``stack`` and exceptions under
    ``exception``, both before and after ``LoggingService`` swaps in the queued pipeline.
    """

    def render_json(self, emit: Callable[[], None], *, queued: bool) -> dict[str, Any]:
        return json.loads(render("json", emit, queued=queued).strip().splitlines()[-1])

    def test_stdlib_stack_info_is_rendered(self, queued: bool) -> None:
        stdlib_logger = logging.getLogger(STDLIB_LOGGER_NAME)
        record = self.render_json(lambda: stdlib_logger.info("where am I", stack_info=True), queued=queued)
        assert record["event"] == "where am I", record
        assert "stack_info" not in record, record
        assert "Stack (most recent call last):" in record["stack"], record
        assert "test_stdlib_stack_info_is_rendered" in record["stack"], record

    def test_structlog_stack_info_is_rendered(self, queued: bool) -> None:
        native = structlog.get_logger(NATIVE_LOGGER_NAME)
        record = self.render_json(lambda: native.info("where am I", stack_info=True), queued=queued)
        assert record["event"] == "where am I", record
        assert "stack_info" not in record, record
        assert "Stack (most recent call last):" in record["stack"], record
        assert "test_structlog_stack_info_is_rendered" in record["stack"], record

    def test_stdlib_exception_is_rendered(self, queued: bool) -> None:
        stdlib_logger = logging.getLogger(STDLIB_LOGGER_NAME)
        record = self.render_json(lambda: log_caught_error(stdlib_logger), queued=queued)
        assert record["event"] == "failed", record
        assert "exc_info" not in record, record
        assert "ValueError: kaboom" in record["exception"], record

    @pytest.mark.parametrize("via_exc_info", [False, True], ids=["exception", "error_exc_info"])
    def test_structlog_exception_is_rendered(self, queued: bool, via_exc_info: bool) -> None:
        native = structlog.get_logger(NATIVE_LOGGER_NAME)
        record = self.render_json(lambda: log_caught_error(native, via_exc_info=via_exc_info), queued=queued)
        assert record["event"] == "failed", record
        assert "exc_info" not in record, record
        assert "ValueError: kaboom" in record["exception"], record


@pytest.mark.parametrize("queued", [False, True], ids=["sync", "queued"])
@pytest.mark.parametrize("log_format", ["console", "compact"])
class TestConsoleException:
    """Console formats render the traceback for stdlib and structlog-native callers in both pipeline phases."""

    def test_stdlib_exception_is_rendered(self, queued: bool, log_format: LogFormat) -> None:
        stdlib_logger = logging.getLogger(STDLIB_LOGGER_NAME)
        output = render(log_format, lambda: log_caught_error(stdlib_logger), queued=queued)
        assert "Traceback" in output, output
        assert "ValueError: kaboom" in output, output

    def test_structlog_exception_is_rendered(self, queued: bool, log_format: LogFormat) -> None:
        native = structlog.get_logger(NATIVE_LOGGER_NAME)
        output = render(log_format, lambda: log_caught_error(native), queued=queued)
        assert "Traceback" in output, output
        assert "ValueError: kaboom" in output, output


class TestQueuedPersistedRow:
    """The row ``LogPersistenceHandler`` builds from a record that crossed the Phase 2 queue."""

    def persisted_row(self, emit: Callable[[], None]) -> dict[str, Any]:
        collected: list[logging.LogRecord] = []
        collector = logging.Handler()
        collector.emit = collected.append  # pyright: ignore[reportAttributeAccessIssue]
        stream_handler = enable_basic_logging("INFO", log_format="json", stream=StringIO())
        with queued_pipeline(stream_handler, collector):
            emit()
        persistence = LogPersistenceHandler(MagicMock(), MagicMock(), persistence_level=logging.DEBUG)
        return persistence.record_to_dict(collected[-1])

    def test_structlog_message_is_the_event(self) -> None:
        native = structlog.get_logger(NATIVE_LOGGER_NAME)
        row = self.persisted_row(lambda: native.info("door opened", door="front"))
        assert row["message"] == "door opened", row

    def test_structlog_stack_is_appended_to_message(self) -> None:
        native = structlog.get_logger(NATIVE_LOGGER_NAME)
        row = self.persisted_row(lambda: native.info("where am I", stack_info=True))
        assert row["message"].startswith("where am I\nStack (most recent call last):"), row
        assert "test_structlog_stack_is_appended_to_message" in row["message"], row

    def test_stdlib_stack_is_appended_to_message(self) -> None:
        stdlib_logger = logging.getLogger(STDLIB_LOGGER_NAME)
        row = self.persisted_row(lambda: stdlib_logger.info("where am I %s", "now", stack_info=True))
        assert row["message"].startswith("where am I now\nStack (most recent call last):"), row

    def test_stdlib_exception_lands_in_exc_info(self) -> None:
        stdlib_logger = logging.getLogger(STDLIB_LOGGER_NAME)
        row = self.persisted_row(lambda: log_caught_error(stdlib_logger))
        assert row["message"] == "failed", row
        assert "ValueError: kaboom" in row["exc_info"], row

    @pytest.mark.parametrize("via_exc_info", [False, True], ids=["exception", "error_exc_info"])
    def test_structlog_exception_lands_in_exc_info(self, via_exc_info: bool) -> None:
        native = structlog.get_logger(NATIVE_LOGGER_NAME)
        row = self.persisted_row(lambda: log_caught_error(native, via_exc_info=via_exc_info))
        assert row["message"] == "failed", row
        assert "ValueError: kaboom" in row["exc_info"], row


@contextmanager
def execution_scope(execution_id: str, *, instance_name: str) -> Iterator[None]:
    """Bind an execution id and an app subject the way command_executor does around a handler run."""
    token = CURRENT_EXECUTION_ID.set(execution_id)
    structlog.contextvars.bind_contextvars(instance_name=instance_name)
    try:
        yield
    finally:
        structlog.contextvars.unbind_contextvars("instance_name")
        CURRENT_EXECUTION_ID.reset(token)


class TestNoisyLibrarySuppression:
    """Noisy library suppression still works after structlog migration."""

    def test_requests_logger_at_warning(self) -> None:
        stream = StringIO()
        enable_basic_logging("INFO", log_format="console", stream=stream)
        assert logging.getLogger("requests").level == logging.WARNING

    def test_urllib3_logger_at_warning(self) -> None:
        stream = StringIO()
        enable_basic_logging("INFO", log_format="console", stream=stream)
        assert logging.getLogger("urllib3").level == logging.WARNING

    def test_aiohttp_access_logger_at_warning(self) -> None:
        stream = StringIO()
        enable_basic_logging("INFO", log_format="console", stream=stream)
        assert logging.getLogger("aiohttp.access").level == logging.WARNING

    def test_httpx_logger_at_warning(self) -> None:
        stream = StringIO()
        enable_basic_logging("INFO", log_format="console", stream=stream)
        assert logging.getLogger("httpx2").level == logging.WARNING


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
        assert logging.getLogger("requests").level == logging.WARNING
        assert logging.getLogger("urllib3").level == logging.WARNING
        assert logging.getLogger("aiohttp.access").level == logging.WARNING
        assert logging.getLogger("httpx2").level == logging.WARNING

    def test_json_format_selected(self) -> None:
        """enable_basic_logging() supports log_format='json'."""
        stream = StringIO()
        enable_basic_logging("INFO", log_format="json", stream=stream)
        logger = logging.getLogger("hassette.test_basic_json")
        logger.info("json basic test")
        assert last_json_record(stream)["event"] == "json basic test"

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
        assert logging.getLogger("requests").level == logging.WARNING

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


def _installed_renderer() -> object:
    """Return the final processor of the formatter on the stream handler enable_basic_logging installed."""
    handlers = logging.getLogger(HASSETTE_LOGGER_NAME).handlers
    stream_handlers = [h for h in handlers if isinstance(h, logging.StreamHandler)]
    assert len(stream_handlers) == 1, f"expected one stream handler on the hassette logger, got {handlers}"
    formatter = stream_handlers[0].formatter
    assert isinstance(formatter, structlog.stdlib.ProcessorFormatter)
    return formatter.processors[-1]
