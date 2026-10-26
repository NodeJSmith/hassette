"""Stacks, exceptions and persisted rows for records rendered before and after the Phase 2 log queue.

``LoggingService`` swaps ``enable_basic_logging``'s stream handler for ``HassetteQueueHandler`` →
``HassetteQueueListener``, which renders on a background thread. These tests run each case through both
pipelines: synchronous (Phase 1) and queued (Phase 2).
"""

import json
import logging
import queue
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from io import StringIO
from typing import Any
from unittest.mock import MagicMock

import pytest
import structlog

from hassette.const import HASSETTE_LOGGER_NAME
from hassette.logging_ import (
    CorrelationFilter,
    HassetteQueueHandler,
    HassetteQueueListener,
    LogFormat,
    LogIdentityFilter,
    LogPersistenceHandler,
    enable_basic_logging,
)

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")
STDLIB_LOGGER_NAME = "hassette.apps.example_stdlib"
NATIVE_LOGGER_NAME = "hassette.apps.example_native"
# A local in the frame that logs an exception; console tracebacks must not print it.
HELD_LOCAL_VALUE = "local-value-not-for-logs"
# A creation time long past, so a timestamp taken from the clock at render time can't match it.
PAST_CREATED = datetime(2020, 1, 2, 3, 4, 5, 500000).timestamp()


@contextmanager
def queued_pipeline(stream_handler: logging.Handler, *extra_handlers: logging.Handler) -> Iterator[None]:
    """Swap the hassette logger's ``stream_handler`` for the Phase 2 queue, as ``LoggingService`` does.

    The queue's listener feeds ``stream_handler`` and ``extra_handlers``. This changes the process-wide
    hassette logger, so the ``finally`` puts ``stream_handler`` back.
    """
    logger = logging.getLogger(HASSETTE_LOGGER_NAME)
    log_queue: queue.Queue[logging.LogRecord] = queue.Queue()
    queue_handler = HassetteQueueHandler(log_queue)
    queue_handler.addFilter(LogIdentityFilter())
    queue_handler.addFilter(CorrelationFilter())
    listener = HassetteQueueListener(log_queue, stream_handler, *extra_handlers)
    logger.addHandler(queue_handler)
    logger.removeHandler(stream_handler)
    listener.start()
    try:
        yield
    finally:
        listener.stop()
        logger.removeHandler(queue_handler)
        logger.addHandler(stream_handler)


class RecordCollector(logging.Handler):
    """Keeps every record it receives, as the listener hands them to its handlers."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def log_caught_error(logger: Any, *, via_exc_info: bool = False) -> None:
    """Log ``"failed"`` while a ``ValueError("kaboom")`` is being handled.

    ``via_exc_info`` logs with ``error(..., exc_info=True)`` instead of ``exception()``.
    """
    held_local = HELD_LOCAL_VALUE  # noqa: F841  # pyright: ignore[reportUnusedVariable] - a frame local the traceback must not print
    try:
        raise ValueError("kaboom")
    except ValueError:
        if via_exc_info:
            logger.error("failed", exc_info=True)  # noqa: G201 - the exc_info=True path is under test
        else:
            logger.exception("failed")


def render_pipeline(log_format: LogFormat, emit: Callable[[], None], *, queued: bool) -> str:
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
        return json.loads(render_pipeline("json", emit, queued=queued).strip().splitlines()[-1])

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
        output = render_pipeline(log_format, lambda: log_caught_error(stdlib_logger), queued=queued)
        assert "Traceback" in output, output
        assert "ValueError: kaboom" in output, output
        assert HELD_LOCAL_VALUE not in output, output

    def test_structlog_exception_is_rendered(self, queued: bool, log_format: LogFormat) -> None:
        native = structlog.get_logger(NATIVE_LOGGER_NAME)
        output = render_pipeline(log_format, lambda: log_caught_error(native), queued=queued)
        assert "Traceback" in output, output
        assert "ValueError: kaboom" in output, output
        assert HELD_LOCAL_VALUE not in output, output


def log_created_at(logger: logging.Logger, created: float) -> None:
    """Log ``"stamped"`` through ``logger`` from a record whose creation time is ``created``."""
    record = logger.makeRecord(logger.name, logging.INFO, __file__, 0, "stamped", (), None)
    record.created = created
    logger.handle(record)


@pytest.mark.parametrize("queued", [False, True], ids=["sync", "queued"])
class TestStdlibTimestamp:
    """A stdlib record's rendered timestamp is its creation time, not the time it was rendered."""

    def test_json_timestamp_is_record_created(self, queued: bool) -> None:
        stdlib_logger = logging.getLogger(STDLIB_LOGGER_NAME)
        output = render_pipeline("json", lambda: log_created_at(stdlib_logger, PAST_CREATED), queued=queued)
        record = json.loads(output.strip().splitlines()[-1])
        assert record["timestamp"] == "2020-01-02T03:04:05.500000", record

    @pytest.mark.parametrize(
        ("log_format", "expected"), [("console", "2020-01-02T03:04:05.500000"), ("compact", "03:04:05")]
    )
    def test_console_timestamp_is_record_created(self, queued: bool, log_format: LogFormat, expected: str) -> None:
        stdlib_logger = logging.getLogger(STDLIB_LOGGER_NAME)
        output = render_pipeline(log_format, lambda: log_created_at(stdlib_logger, PAST_CREATED), queued=queued)
        line = output.strip().splitlines()[-1]
        assert line.startswith(expected), line
        assert "stamped" in line, line


class TestQueuedPersistedRow:
    """The row ``LogPersistenceHandler`` builds from a record that crossed the Phase 2 queue."""

    def persisted_row(self, emit: Callable[[], None]) -> dict[str, Any]:
        collector = RecordCollector()
        stream_handler = enable_basic_logging("INFO", log_format="json", stream=StringIO())
        with queued_pipeline(stream_handler, collector):
            emit()
        # record_to_dict only reads the record; the database and loop are never touched.
        persistence = LogPersistenceHandler(db_service=MagicMock(), loop=MagicMock(), persistence_level=logging.DEBUG)
        return persistence.record_to_dict(collector.records[-1])

    def test_structlog_message_is_the_event(self) -> None:
        native = structlog.get_logger(NATIVE_LOGGER_NAME)
        row = self.persisted_row(lambda: native.info("door opened", door="front"))
        assert row["message"] == "door opened", row

    def test_stdlib_dict_message_is_kept(self) -> None:
        """A stdlib caller logging a dict isn't mistaken for a structlog record with no ``event``."""
        stdlib_logger = logging.getLogger(STDLIB_LOGGER_NAME)
        row = self.persisted_row(lambda: stdlib_logger.info({"door": "front"}))
        assert row["message"] == "{'door': 'front'}", row

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
