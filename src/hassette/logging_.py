import asyncio
import contextlib
import itertools
import logging
import logging.handlers
import queue
import sys
import threading
import traceback
from collections import deque
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import IO, TYPE_CHECKING, Any, Literal

import structlog
import structlog.dev
import structlog.processors
import structlog.stdlib
import structlog.types

from hassette.context import CURRENT_EXECUTION_ID

MAX_SNAPSHOT_RETRIES = 5
DEQUEUE_TIMEOUT_SECONDS = 0.2

if TYPE_CHECKING:
    from hassette.core.database_service import DatabaseService


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

    def to_dict(self) -> dict[str, Any]:
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


def _extract_correlation_attrs(record: logging.LogRecord) -> dict[str, Any]:
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
    _broadcast_fn: Callable[[dict], Coroutine[Any, Any, None]] | None
    _loop: asyncio.AbstractEventLoop | None

    shutting_down: bool

    def __init__(self, buffer_size: int = 2000) -> None:
        super().__init__()
        self._buffer = deque(maxlen=buffer_size)
        self._broadcast_fn = None
        self._loop = None
        self.shutting_down = False

    @property
    def buffer(self) -> deque[LogEntry]:
        return self._buffer

    def get_buffer_snapshot(self) -> list[LogEntry]:
        """Return a thread-safe snapshot of the buffer.

        The underlying deque can be mutated by emit() from worker threads,
        so iterating it directly risks RuntimeError. This retries on mutation.
        """
        for _ in range(MAX_SNAPSHOT_RETRIES):
            try:
                return list(self._buffer)
            except RuntimeError:
                continue
        return []

    def set_broadcast(self, fn: Callable[[dict], Coroutine[Any, Any, None]], loop: asyncio.AbstractEventLoop) -> None:
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
        if self.shutting_down:
            return
        if self._broadcast_fn and self._loop and self._loop.is_running():
            fn = self._broadcast_fn
            loop = self._loop
            # LogWsMessage requires a top-level timestamp; entry.to_dict() only nests one under data.
            payload = {"type": "log", "data": entry.to_dict(), "timestamp": entry.timestamp}

            def _schedule_broadcast() -> None:
                with contextlib.suppress(RuntimeError):
                    loop.create_task(fn(payload))

            loop.call_soon_threadsafe(_schedule_broadcast)


class CorrelationFilter(logging.Filter):
    """Stamps correlation IDs and seq on log records before they leave the calling context.

    Attached to the ``QueueHandler`` (not the logger) so it runs for records propagated from
    child loggers. Reads context vars in the calling thread before the background-thread handoff.

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
        if not getattr(record, "source_tier", None):
            record.source_tier = "app" if record.app_key else "framework"  # pyright: ignore[reportAttributeAccessIssue]
        return True


class HassetteQueueListener(logging.handlers.QueueListener):
    """QueueListener with dequeue-timeout for periodic batch flushing.

    The default QueueListener blocks forever on dequeue(). This subclass adds a timeout
    so the listener thread periodically wakes up and flushes partial batches in handlers that
    support ``flush_if_pending()``.
    """

    def dequeue(self, block: bool) -> logging.LogRecord:
        return self.queue.get(block=block, timeout=DEQUEUE_TIMEOUT_SECONDS)  # pyright: ignore[reportCallIssue]

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

    Receives ``db_service`` and ``loop`` at construction — ready to persist immediately.
    """

    _db_service: "DatabaseService"
    _loop: asyncio.AbstractEventLoop
    _batch: list[dict]
    _dropped: int
    _persistence_level: int

    BATCH_SIZE: int = 50

    def __init__(
        self,
        db_service: "DatabaseService",
        loop: asyncio.AbstractEventLoop,
        persistence_level: int = logging.INFO,
    ) -> None:
        super().__init__()
        self._db_service = db_service
        self._loop = loop
        self._batch = []
        self._dropped = 0
        self._dropped_lock = threading.Lock()
        self._persistence_level = persistence_level

    @property
    def dropped_count(self) -> int:
        with self._dropped_lock:
            return self._dropped

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < self._persistence_level:
            return
        self._batch.append(self.record_to_dict(record))
        if len(self._batch) >= self.BATCH_SIZE:
            self._flush()

    def flush_if_pending(self) -> None:
        if self._batch:
            self._flush()

    def _flush(self) -> None:
        batch = self._batch
        self._batch = []
        db_service = self._db_service
        loop = self._loop
        dropped_lock = self._dropped_lock
        batch_len = len(batch)

        def _do_enqueue(b=batch) -> None:
            try:
                if not db_service.enqueue(db_service._insert_log_records(b)):
                    with dropped_lock:
                        self._dropped += batch_len
            except RuntimeError:
                with dropped_lock:
                    self._dropped += batch_len

        try:
            loop.call_soon_threadsafe(_do_enqueue)
        except RuntimeError:
            with dropped_lock:
                self._dropped += batch_len

    def record_to_dict(self, record: logging.LogRecord) -> dict[str, Any]:
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
        # Flushes remaining records via call_soon_threadsafe — the enqueued
        # coroutine may not execute if the event loop is already stopping.
        # LoggingService.on_shutdown() flushes pending records before stopping.
        self.flush_if_pending()
        super().close()


def add_execution_id(
    _logger: object,
    _method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Structlog processor: stamp execution_id from CURRENT_EXECUTION_ID context var.

    Inserted in the shared processor chain after TimeStamper so structlog-native callers
    carry the execution correlation identifier. Stdlib callers rely on CorrelationFilter
    instead (the processor chain does not run for them until ProcessorFormatter picks them
    up, which is after the calling context).
    """
    event_dict["execution_id"] = CURRENT_EXECUTION_ID.get(None)
    return event_dict


_RECORD_FIELDS = ("source_tier", "app_key", "execution_id", "instance_name", "instance_index")


def _extract_record_fields(
    _logger: object,
    _method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
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


def enable_basic_logging(
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    *,
    log_format: Literal["auto", "console", "json"] = "auto",
    stream: IO[str] | None = None,
) -> logging.StreamHandler:
    """Set up synchronous console-only structured logging.

    Phase 1 of the two-phase logging model: configures structlog and attaches a
    synchronous ``StreamHandler`` directly to the ``hassette`` logger. No queue,
    no background thread, no persistence. Available immediately — before the
    Resource tree exists.

    ``LoggingService.on_initialize()`` upgrades to the full async pipeline in Phase 2.

    Args:
        log_level: Minimum log level for the hassette logger.
        log_format: Output format selection.
            ``"console"`` always uses ConsoleRenderer (colored human-readable).
            ``"json"`` always uses JSONRenderer (one JSON object per line).
            ``"auto"`` checks ``stream.isatty()`` (defaults to ``sys.stdout``).
        stream: Output stream. Defaults to ``sys.stdout``.

    Returns:
        The StreamHandler attached to the hassette logger. Stored on Hassette and
        passed to LoggingService for the Phase 2 sync→async swap.
    """
    out: IO[str] = stream if stream is not None else sys.stdout

    if log_format == "json":
        use_json = True
    elif log_format == "console":
        use_json = False
    else:
        use_json = not out.isatty()

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=False),
        add_execution_id,
    ]

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

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            _extract_record_fields,
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    logger = logging.getLogger("hassette")
    logger.setLevel(log_level)
    logger.propagate = False
    logger.handlers.clear()
    logger.filters.clear()

    stream_handler = logging.StreamHandler(out)
    stream_handler.setLevel(logging.NOTSET)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    # Capture warnings.warn(...) and friends messages in logs.
    logging.captureWarnings(True)

    # Suppress overly verbose logs from libraries that aren't helpful
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.ERROR)

    sys.excepthook = lambda *args: logging.getLogger().exception("Uncaught exception", exc_info=args)
    threading.excepthook = lambda args: logging.getLogger().exception(
        "Uncaught thread exception",
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),  # pyright: ignore[reportArgumentType]
    )

    return stream_handler
