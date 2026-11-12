"""Shared test factories for log records, log entries, and log-capture handlers."""

import logging
from typing import Any

from hassette_wire import LogAuthor

from hassette.logging_ import (
    LogCaptureHandler,
    LogIdentityFilter,
    LogRecordEntry,
    _extract_correlation_attrs,  # pyright: ignore[reportPrivateUsage]
)
from hassette.logging_processors import persisted_exc_text, persisted_message


def make_log_record_entry(
    *,
    seq: int = 1,
    timestamp: float = 0.0,
    level: str = "INFO",
    logger_name: str = "hassette.test",
    func_name: str = "fn",
    lineno: int = 1,
    message: str = "msg",
    exc_info: str | None = None,
    app_key: str | None = None,
    author: LogAuthor = "app",
    execution_id: str | None = None,
    instance_name: str | None = None,
) -> LogRecordEntry:
    """Build a `LogRecordEntry`, defaulting every required field to a neutral placeholder.

    `LogRecordEntry` has eight required constructor fields, most of which are irrelevant to any
    given assertion, plus five optional fields (`exc_info`, plus four correlation fields).
    Every field is an explicit keyword so callers spell out only what they assert on and
    pyright still checks the rest.
    """
    return LogRecordEntry(
        seq=seq,
        timestamp=timestamp,
        level=level,
        logger_name=logger_name,
        func_name=func_name,
        lineno=lineno,
        message=message,
        exc_info=exc_info,
        app_key=app_key,
        author=author,
        execution_id=execution_id,
        instance_name=instance_name,
    )


def make_log_record_dict(
    *,
    seq: int = 1,
    timestamp: float = 0.0,
    level: str = "INFO",
    logger_name: str = "hassette.test",
    func_name: str = "fn",
    lineno: int = 1,
    message: str = "msg",
    exc_info: str | None = None,
    app_key: str | None = None,
    instance_name: str | None = None,
    execution_id: str | None = None,
    author: LogAuthor = "app",
) -> dict[str, Any]:
    """Build the 13-key record dict shape ``insert_log_records()`` expects.

    Every field is an explicit keyword with a neutral default so callers spell out only
    what they assert on.
    """
    return {
        "seq": seq,
        "timestamp": timestamp,
        "level": level,
        "logger_name": logger_name,
        "func_name": func_name,
        "lineno": lineno,
        "message": message,
        "exc_info": exc_info,
        "app_key": app_key,
        "instance_name": instance_name,
        "execution_id": execution_id,
        "author": author,
    }


def make_log_record(
    *,
    name: str = "test",
    level: int = logging.INFO,
    pathname: str = "",
    lineno: int = 0,
    msg: str = "msg",
    args: tuple[Any, ...] = (),
    exc_info: Any = None,
    author: LogAuthor | None = "app",
) -> logging.LogRecord:
    """Build a ``logging.LogRecord`` with sensible defaults.

    Replaces the 7-positional-arg ``logging.LogRecord(...)`` calls scattered across logging
    test files. Every field is an explicit keyword so callers spell out only what matters.

    ``author`` is stamped as ``LogIdentityFilter`` would stamp it, since every record a Hassette handler
    sees has passed that filter. Pass ``None`` for a record that skipped it.
    """
    record = logging.LogRecord(name, level, pathname, lineno, msg, args, exc_info)
    if author is not None:
        record.author = author  # pyright: ignore[reportAttributeAccessIssue]
    return record


def build_log_entry(record: logging.LogRecord) -> LogRecordEntry:
    """Build a LogRecordEntry from a LogRecord using the correlation attrs and formatted traceback.

    Test-only: production `LogCaptureHandler.emit()` only needs `record.created` and builds its
    broadcast payload directly. This assembles the full `LogRecordEntry` shape for tests that need to
    assert on correlation attrs and message content.
    """
    attrs = _extract_correlation_attrs(record)
    return LogRecordEntry(
        timestamp=record.created,
        level=record.levelname,
        logger_name=record.name,
        func_name=record.funcName or "",
        lineno=record.lineno,
        message=persisted_message(record),
        exc_info=persisted_exc_text(record),
        **attrs,
    )


class RecordingLogCaptureHandler(LogCaptureHandler):
    """A `LogCaptureHandler` that also records every `LogRecordEntry` it builds, for test assertions.

    Production `LogCaptureHandler` no longer retains captured entries (see `build_log_entry`) —
    it only broadcasts a hint. Tests that need to inspect the constructed `LogRecordEntry` objects
    (correlation attrs, message content, shutdown-guard behavior) use this subclass as their
    observation seam instead.

    In production, records reach the capture handler through the queue handler's `LogIdentityFilter`.
    This handler carries the filter itself, so records logged straight to it get an author the same way.
    Calling `emit()` directly skips handler filters, so those callers stamp `author` themselves.
    """

    def __init__(self) -> None:
        super().__init__()
        self.captured: list[LogRecordEntry] = []
        self.addFilter(LogIdentityFilter())

    def emit(self, record: logging.LogRecord) -> None:
        self.captured.append(build_log_entry(record))
        super().emit(record)


def make_recording_log_capture_handler() -> RecordingLogCaptureHandler:
    """Build a `RecordingLogCaptureHandler` for observing `LogCaptureHandler.emit()` behavior."""
    return RecordingLogCaptureHandler()
