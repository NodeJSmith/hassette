import asyncio
import itertools
import logging
import logging.handlers
import queue
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

from hassette.context import CURRENT_EXECUTION_ID
from hassette.core import telemetry_repository as _telemetry_repository

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
    execution_id: str | None = None
    instance_name: str | None = None
    instance_index: int | None = None

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
            "execution_id": self.execution_id,
            "instance_name": self.instance_name,
            "instance_index": self.instance_index,
        }


def _extract_correlation_attrs(record: logging.LogRecord) -> dict:
    """Extract correlation attributes stamped by CorrelationFilter from a LogRecord."""
    return {
        "app_key": getattr(record, "app_key", None),
        "source_tier": getattr(record, "source_tier", None),
        "execution_id": getattr(record, "execution_id", None),
        "instance_name": getattr(record, "instance_name", None),
        "instance_index": getattr(record, "instance_index", None),
        "seq": getattr(record, "seq", 0),
    }


class LogCaptureHandler(logging.Handler):
    """Captures log records into a bounded deque and broadcasts to WS clients."""

    _buffer: deque[LogEntry]
    _broadcast_fn: Callable[[dict], Awaitable[None]] | None
    _loop: asyncio.AbstractEventLoop | None

    _shutting_down: bool

    def __init__(self, buffer_size: int = 2000) -> None:
        super().__init__()
        self._buffer = deque(maxlen=buffer_size)
        self._broadcast_fn = None
        self._loop = None
        self._shutting_down = False

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
        attrs = _extract_correlation_attrs(record)
        entry = LogEntry(
            timestamp=record.created,
            level=record.levelname,
            logger_name=record.name,
            func_name=record.funcName or "",
            lineno=record.lineno,
            message=record.getMessage(),
            exc_info="".join(traceback.format_exception(*record.exc_info)) if record.exc_info else None,
            **attrs,
        )
        self._buffer.append(entry)
        if self._shutting_down:
            return
        if self._broadcast_fn and self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(
                self._loop.create_task,
                self._broadcast_fn({"type": "log", "data": entry.to_dict()}),
            )


class CorrelationFilter(logging.Filter):
    """Stamps correlation IDs and seq on log records before they leave the calling context.

    Attached to the ``hassette`` logger (upstream of QueueHandler). Reads context vars in the
    calling async context so the values are captured before the background-thread handoff.

    Stamps:
        - ``execution_id``: from ``CURRENT_EXECUTION_ID`` context var.
        - ``app_key``, ``instance_name``, ``instance_index``: from structlog context vars
          (bound by command_executor and app_lifecycle_service dispatch points).
        - ``seq``: monotonic sequence number for ordering within a session.
    """

    _seq: itertools.count

    def __init__(self) -> None:
        super().__init__()
        self._seq = itertools.count(1)

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = structlog.contextvars.get_contextvars()
        record.execution_id = CURRENT_EXECUTION_ID.get(None)  # pyright: ignore[reportAttributeAccessIssue]
        record.app_key = ctx.get("app_key")  # pyright: ignore[reportAttributeAccessIssue]
        record.instance_name = ctx.get("instance_name")  # pyright: ignore[reportAttributeAccessIssue]
        record.instance_index = ctx.get("instance_index")  # pyright: ignore[reportAttributeAccessIssue]
        record.seq = next(self._seq)  # pyright: ignore[reportAttributeAccessIssue]
        return True


class HassetteQueueListener(logging.handlers.QueueListener):
    """QueueListener with dequeue-timeout for periodic batch flushing.

    The default QueueListener blocks forever on dequeue(). This subclass adds a 200ms timeout
    so the listener thread periodically wakes up and flushes partial batches in handlers that
    support ``flush_if_pending()``.
    """

    def dequeue(self, block: bool) -> logging.LogRecord:
        return self.queue.get(block=block, timeout=0.2)  # pyright: ignore[reportCallIssue]

    def enqueue_sentinel(self) -> None:
        # Blocking put — put_nowait raises queue.Full on a bounded queue during burst logging,
        # preventing sentinel delivery and hanging thread.join() in stop().
        self.queue.put(self._sentinel)  # pyright: ignore[reportAttributeAccessIssue]

    def _monitor(self) -> None:
        q = self.queue
        has_task_done = hasattr(q, "task_done")
        while True:
            try:
                record = self.dequeue(True)
                if record is self._sentinel:  # pyright: ignore[reportAttributeAccessIssue]
                    if has_task_done:
                        q.task_done()  # pyright: ignore[reportAttributeAccessIssue]
                    break
                self.handle(record)
                if has_task_done:
                    q.task_done()  # pyright: ignore[reportAttributeAccessIssue]
            except queue.Empty:
                for handler in self.handlers:
                    if hasattr(handler, "flush_if_pending"):
                        handler.flush_if_pending()  # pyright: ignore[reportAttributeAccessIssue]


class LogPersistenceHandler(logging.Handler):
    """Batches log records for async DB persistence.

    Starts inert (no DB). ``set_database()`` is called later by RuntimeQueryService
    to wire DB access. Until then, records are counted as dropped.
    """

    _db_service: object | None
    _loop: asyncio.AbstractEventLoop | None
    _batch: list[dict]
    _dropped: int
    _persistence_level: int

    BATCH_SIZE: int = 50

    def __init__(self, persistence_level: int = logging.INFO) -> None:
        super().__init__()
        self._db_service = None
        self._loop = None
        self._batch = []
        self._dropped = 0
        self._persistence_level = persistence_level

    def set_database(self, db_service: object, loop: asyncio.AbstractEventLoop) -> None:
        # Called once from the event loop before the listener processes records at this level.
        self._db_service = db_service
        self._loop = loop

    @property
    def dropped_count(self) -> int:
        return self._dropped

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < self._persistence_level:
            return
        self._batch.append(self._record_to_dict(record))
        if len(self._batch) >= self.BATCH_SIZE:
            self._flush()

    def flush_if_pending(self) -> None:
        if self._batch:
            self._flush()

    def _flush(self) -> None:
        batch = self._batch
        self._batch = []
        if self._db_service is None or self._loop is None:
            self._dropped += len(batch)
            return
        db_service = self._db_service
        self._loop.call_soon_threadsafe(
            lambda b=batch: db_service.enqueue(_telemetry_repository.insert_log_records(b)),  # pyright: ignore[reportAttributeAccessIssue]
        )

    def _record_to_dict(self, record: logging.LogRecord) -> dict:
        return {
            "timestamp": record.created,
            "level": record.levelname,
            "logger_name": record.name,
            "func_name": record.funcName or "",
            "lineno": record.lineno,
            "message": record.getMessage(),
            "exc_info": "".join(traceback.format_exception(*record.exc_info)) if record.exc_info else None,
            **_extract_correlation_attrs(record),
        }

    def close(self) -> None:
        self.flush_if_pending()
        super().close()


# Module-level references for shutdown and external wiring
_log_capture_handler: LogCaptureHandler | None = None
_log_persistence_handler: LogPersistenceHandler | None = None
_queue_listener: HassetteQueueListener | None = None


def get_log_capture_handler() -> LogCaptureHandler | None:
    """Return the global LogCaptureHandler instance, if installed."""
    return _log_capture_handler


def get_log_persistence_handler() -> LogPersistenceHandler | None:
    """Return the global LogPersistenceHandler instance, if installed."""
    return _log_persistence_handler


def add_execution_id(_logger: object, _method_name: str, event_dict: dict) -> dict:
    """Structlog processor: stamp execution_id from CURRENT_EXECUTION_ID context var.

    Inserted in the shared processor chain after TimeStamper so structlog-native callers
    carry the execution correlation identifier. Stdlib callers rely on CorrelationFilter
    instead (the processor chain does not run for them until ProcessorFormatter picks them
    up, which is after the calling context).
    """
    event_dict["execution_id"] = CURRENT_EXECUTION_ID.get(None)
    return event_dict


_RECORD_FIELDS = ("source_tier", "app_key", "execution_id", "instance_name", "instance_index")


def _extract_record_fields(_logger: logging.Logger, _method_name: str, event_dict: dict) -> dict:
    """Pull custom attributes stamped by CorrelationFilter from the LogRecord into the event dict.

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
    log_queue_max: int = 2000,
    log_persistence_level: int = logging.INFO,
    stream: IO[str] | None = None,
) -> None:
    """Set up structured logging via structlog's ProcessorFormatter.

    All log I/O runs off the event loop: a ``QueueHandler`` on the hassette logger
    enqueues records (non-blocking), and a background ``HassetteQueueListener`` dispatches
    them to the stream, capture, and persistence handlers.

    Args:
        log_level: Minimum log level for the hassette logger.
        log_buffer_size: Capacity of the in-memory ring buffer for WS broadcast.
        log_format: Output format selection.
            ``"console"`` always uses ConsoleRenderer (colored human-readable).
            ``"json"`` always uses JSONRenderer (one JSON object per line).
            ``"auto"`` checks ``stream.isatty()`` (defaults to ``sys.stdout``).
        log_queue_max: Maximum size of the inter-thread log queue.
        log_persistence_level: Minimum level for DB persistence (default INFO).
        stream: Output stream. Defaults to ``sys.stdout``.
    """
    global _log_capture_handler, _log_persistence_handler, _queue_listener

    # Stop any previously running listener (idempotent re-init)
    shutdown_logging()

    if stream is None:
        stream = sys.stdout

    # --- Determine renderer based on log_format ---
    if log_format == "json":
        use_json = True
    elif log_format == "console":
        use_json = False
    else:
        use_json = not stream.isatty()

    # --- Shared processors applied to all records (structlog and stdlib) ---
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        add_execution_id,
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
    logger.filters.clear()

    # CorrelationFilter: stamps execution_id, app_key, instance_name, instance_index, seq
    # on every record before it is dispatched to any handler. Must be on the logger (not a
    # handler) so it runs in the calling context, reading context vars before any queue handoff.
    logger.addFilter(CorrelationFilter())

    # --- Build handlers for the QueueListener (run in background thread) ---
    stream_handler = logging.StreamHandler(stream)
    stream_handler.setLevel(logging.NOTSET)
    stream_handler.setFormatter(formatter)

    _log_capture_handler = LogCaptureHandler(buffer_size=log_buffer_size)

    _log_persistence_handler = LogPersistenceHandler(persistence_level=log_persistence_level)

    # --- QueueHandler → QueueListener pipeline ---
    q: queue.Queue[logging.LogRecord] = queue.Queue(maxsize=log_queue_max)
    queue_handler = logging.handlers.QueueHandler(q)
    logger.addHandler(queue_handler)

    _queue_listener = HassetteQueueListener(q, stream_handler, _log_capture_handler, _log_persistence_handler)
    _queue_listener.start()

    # Capture warnings.warn(...) and friends messages in logs.
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


def shutdown_logging() -> None:
    """Flush and stop the QueueListener, draining all pending log records.

    Safe to call multiple times or before ``enable_logging()``.
    """
    global _log_capture_handler, _log_persistence_handler, _queue_listener

    if _queue_listener is None:
        return

    if _log_capture_handler is not None:
        _log_capture_handler._shutting_down = True

    _queue_listener.stop()
    _queue_listener = None

    if _log_persistence_handler is not None:
        _log_persistence_handler.flush_if_pending()
