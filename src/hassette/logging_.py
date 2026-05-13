import asyncio
import itertools
import logging
import sys
import threading
import traceback
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import IO, Literal

import structlog
import structlog.dev
import structlog.processors
import structlog.stdlib

FORMAT_DATE = "%Y-%m-%d"
FORMAT_TIME = "%H:%M:%S"
FORMAT_DATETIME = f"{FORMAT_DATE} {FORMAT_TIME}"


@dataclass
class LogEntry:
    """A single captured log record."""

    seq: int
    timestamp: float
    level: str
    logger_name: str
    func_name: str
    lineno: int
    message: str
    exc_info: str | None = None
    app_key: str | None = None
    source_tier: str | None = None

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "timestamp": self.timestamp,
            "level": self.level,
            "logger_name": self.logger_name,
            "func_name": self.func_name,
            "lineno": self.lineno,
            "message": self.message,
            "exc_info": self.exc_info,
            "app_key": self.app_key,
            "source_tier": self.source_tier,
        }


class LogCaptureHandler(logging.Handler):
    """Captures log records into a bounded deque and broadcasts to WS clients."""

    _buffer: deque[LogEntry]
    _broadcast_fn: Callable[[dict], Awaitable[None]] | None
    _loop: asyncio.AbstractEventLoop | None

    def __init__(self, buffer_size: int = 2000) -> None:
        super().__init__()
        self._buffer = deque(maxlen=buffer_size)
        self._broadcast_fn = None
        self._loop = None
        self._seq = itertools.count(1)

    @property
    def buffer(self) -> deque[LogEntry]:
        return self._buffer

    def get_buffer_snapshot(self) -> list[LogEntry]:
        """Return a thread-safe snapshot of the buffer.

        The underlying deque can be mutated by emit() from worker threads,
        so iterating it directly risks RuntimeError. This retries on mutation.
        """
        while True:
            try:
                return list(self._buffer)
            except RuntimeError:
                # deque mutated during iteration; retry
                continue

    def set_broadcast(self, fn: Callable[[dict], Awaitable[None]], loop: asyncio.AbstractEventLoop) -> None:
        """Called by RuntimeQueryService after initialization to wire up WS broadcast."""
        self._broadcast_fn = fn
        self._loop = loop

    def emit(self, record: logging.LogRecord) -> None:
        source_tier: str | None = getattr(record, "source_tier", None)
        app_key: str | None = getattr(record, "app_key", None)
        entry = LogEntry(
            seq=next(self._seq),
            timestamp=record.created,
            level=record.levelname,
            logger_name=record.name,
            func_name=record.funcName or "",
            lineno=record.lineno,
            message=record.getMessage(),
            exc_info="".join(traceback.format_exception(*record.exc_info)) if record.exc_info else None,
            app_key=app_key,
            source_tier=source_tier,
        )
        self._buffer.append(entry)
        if self._broadcast_fn and self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(
                self._loop.create_task,
                self._broadcast_fn({"type": "log", "data": entry.to_dict()}),
            )


# Module-level reference so RuntimeQueryService can find it
_log_capture_handler: LogCaptureHandler | None = None


def get_log_capture_handler() -> LogCaptureHandler | None:
    """Return the global LogCaptureHandler instance, if installed."""
    return _log_capture_handler


_RECORD_FIELDS = ("source_tier", "app_key")


def _extract_record_fields(_logger: logging.Logger, _method_name: str, event_dict: dict) -> dict:
    """Pull custom attributes stamped by _ResourceContextFilter from the LogRecord into the event dict.

    Runs in ProcessorFormatter's processors list (before remove_processors_meta) where _record is available.
    """
    record = event_dict.get("_record")
    if record:
        for key in _RECORD_FIELDS:
            val = getattr(record, key, None)
            if val is not None:
                event_dict[key] = val
    return event_dict


def enable_logging(
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    log_buffer_size: int = 2000,
    log_format: Literal["auto", "console", "json"] = "auto",
    stream: IO[str] | None = None,
) -> None:
    """Set up structured logging via structlog's ProcessorFormatter.

    Args:
        log_level: Minimum log level for the hassette logger.
        log_buffer_size: Capacity of the in-memory ring buffer for WS broadcast.
        log_format: Output format selection.
            ``"console"`` always uses ConsoleRenderer (colored human-readable).
            ``"json"`` always uses JSONRenderer (one JSON object per line).
            ``"auto"`` checks ``stream.isatty()`` (defaults to ``sys.stdout``).
        stream: Output stream. Defaults to ``sys.stdout``.
    """
    global _log_capture_handler

    if stream is None:
        stream = sys.stdout

    # --- Determine renderer based on log_format ---
    if log_format == "json":
        use_json = True
    elif log_format == "console":
        use_json = False
    else:
        # "auto": use isatty() to detect terminal vs pipe
        use_json = not stream.isatty()

    # --- Shared processors applied to all records (structlog and stdlib) ---
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    # --- Configure structlog global settings ---
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    renderer = structlog.processors.JSONRenderer() if use_json else structlog.dev.ConsoleRenderer()

    # --- Create ProcessorFormatter with foreign_pre_chain for stdlib records ---
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            _extract_record_fields,
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    # --- Set up hassette root logger ---
    logger = logging.getLogger("hassette")
    logger.setLevel(log_level)
    logger.propagate = False
    logger.handlers.clear()

    # Console/JSON stream handler
    stream_handler = logging.StreamHandler(stream)
    stream_handler.setLevel(logging.NOTSET)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    # Install log capture handler for web UI
    _log_capture_handler = LogCaptureHandler(buffer_size=log_buffer_size)
    logger.addHandler(_log_capture_handler)

    # Capture warnings.warn(...) and friends messages in logs.
    # The standard destination for them is stderr, which may end up unnoticed.
    logging.captureWarnings(True)

    # Suppress overly verbose logs from libraries that aren't helpful
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    sys.excepthook = lambda *args: logging.getLogger().exception("Uncaught exception", exc_info=args)
    threading.excepthook = lambda args: logging.getLogger().exception(
        "Uncaught thread exception",
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),  # pyright: ignore[reportArgumentType]
    )
