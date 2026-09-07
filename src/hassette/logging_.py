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

DEQUEUE_TIMEOUT_SECONDS = 0.2

HASSETTE_LOGGER_NAME = "hassette"
# logging.captureWarnings(True) routes warnings.warn(...) calls (e.g.
# HassetteForgottenAwaitWarning) to this logger. It must stay wired to the same handlers
# as HASSETTE_LOGGER_NAME — see enable_basic_logging() below and LoggingService in
# logging_service.py, which keep both loggers in sync through both phases of the logging model.
PY_WARNINGS_LOGGER_NAME = "py.warnings"
LOGGER_NAMES = (HASSETTE_LOGGER_NAME, PY_WARNINGS_LOGGER_NAME)

# Names LoggingConfig.extra_loggers may not contain — both are already managed outright by
# enable_basic_logging()/LoggingService, and letting a user re-adopt them via extra_loggers
# would silently override level/handler wiring the framework depends on (e.g. py.warnings
# must stay independent of log_level — see the comment on its setup below). Enforced in
# LoggingConfig.reject_reserved_logger_name (config/models.py); duplicated here as the
# single source of truth both that validator and this module read from.
RESERVED_EXTRA_LOGGER_NAMES = frozenset(LOGGER_NAMES)

if TYPE_CHECKING:
    from hassette.core.database_service import DatabaseService


_RECORD_FIELDS = (
    "source_tier",
    "app_key",
    "execution_id",
    "instance_name",
    "instance_index",
    "execution_kind",
    "listener_id",
    "job_id",
)


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
    execution_kind: str | None = None
    listener_id: int | None = None
    job_id: int | None = None

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
            "execution_kind": self.execution_kind,
            "listener_id": self.listener_id,
            "job_id": self.job_id,
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
        "execution_kind": getattr(record, "execution_kind", None),
        "listener_id": getattr(record, "listener_id", None),
        "job_id": getattr(record, "job_id", None),
    }


def _format_exc_info(record: logging.LogRecord) -> str | None:
    if record.exc_info:
        return "".join(traceback.format_exception(*record.exc_info))
    return None


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
            exc_info=_format_exc_info(record),
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
        record.execution_kind = ctx.get("execution_kind")  # pyright: ignore[reportAttributeAccessIssue]
        record.listener_id = ctx.get("listener_id")  # pyright: ignore[reportAttributeAccessIssue]
        record.job_id = ctx.get("job_id")  # pyright: ignore[reportAttributeAccessIssue]
        record.seq = next(self._seq)  # pyright: ignore[reportAttributeAccessIssue]
        if not getattr(record, "source_tier", None):
            record.source_tier = "app" if record.app_key else "framework"  # pyright: ignore[reportAttributeAccessIssue]
        return True


class HassetteQueueHandler(logging.handlers.QueueHandler):
    """QueueHandler that counts records dropped when the bounded log queue is full.

    The stdlib handler routes ``queue.Full`` into ``handleError()``, which loses the drop.
    Counting it here lets operators tell log-queue saturation (tune ``log_queue_max``) apart
    from DB-write-queue saturation, which ``LogPersistenceHandler`` counts separately.
    """

    def __init__(self, queue: queue.Queue[logging.LogRecord]) -> None:
        super().__init__(queue)
        self._dropped = 0
        self._dropped_lock = threading.Lock()

    @property
    def log_queue_drops(self) -> int:
        """Cumulative count of records dropped because the log queue was full."""
        with self._dropped_lock:
            return self._dropped

    def enqueue(self, record: logging.LogRecord) -> None:
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            with self._dropped_lock:
                self._dropped += 1


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
    def db_write_queue_drops(self) -> int:
        """Cumulative count of records dropped because the DB write queue was full or gone."""
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
            "exc_info": _format_exc_info(record),
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


@dataclass(frozen=True)
class _ExtraLoggerSnapshot:
    """The pre-Hassette state of a ``LoggingConfig.extra_loggers`` name.

    Captured once, the first time a given name is ever adopted in this process, before
    ``_reset_logger`` touches it — so it can be restored exactly if a later
    ``enable_basic_logging()`` call (a second ``Hassette()`` constructed in the same process
    with a different or empty ``extra_loggers`` list) stops configuring that name.
    """

    level: int
    propagate: bool
    disabled: bool
    handlers: list[logging.Handler]
    # logging.Filterer.filters is list[Filter | Callable[[LogRecord], bool]] — a plain `list`
    # of that union is invariant against stdlib's own private type alias, so pyright rejects
    # round-tripping it through logger.filters either direction. Any: we only ever store and
    # replay this list verbatim, never inspect its contents.
    filters: list[Any]


# Deliberately module-level, not instance state — see TestNoModuleGlobals for the general
# "no module globals in this file" convention this departs from. That convention targets state
# an owning Resource can hold instead (LoggingService's Phase 2 handlers are instance attributes
# for exactly that reason). This state is different in kind: it exists to detect drift *between*
# separate enable_basic_logging() calls — i.e. separate Hassette() instances constructed one
# after another in the same process, most commonly across test-suite construction. Each such
# instance gets its own LoggingService, so no single instance could own "what the previous
# instance configured" — only state that outlives any one instance and spans the whole process
# can answer that, which is what module-level state means here. logging.getLogger()'s own
# registry is process-global for the same reason; this is bookkeeping for the same registry,
# not an independent design choice. block_io_guard.py's _originals/_installed is the existing
# precedent for this pattern (module state tracking mutations to a shared process-global
# resource so they can be undone) — the difference is block_io_guard also tracks an _owner_id
# to detect a *conflicting* second installation, which doesn't apply here: a second Hassette()
# reconfiguring or dropping a name is the intended, correct behavior for this setting, not a
# conflict to flag.
#
# Not safe for concurrent enable_basic_logging() calls — the diff-and-restore sequence below is
# read-modify-write with no lock. Not currently a real scenario: every call site
# (Hassette.__init__, __main__.py) is synchronous, single-threaded, constructor-time code.
# Keyed by logger name. An entry exists only between a name's adoption and its next restore —
# _restore_extra_logger() pops it once replayed, so a later re-adoption of the same name
# snapshots whatever is actually on the logger at that moment, not the original one. Without
# this, a name adopted, dropped, reconfigured by its own owning code, then re-adopted and
# dropped again would restore to the stale first-ever baseline and silently discard that
# legitimate intervening reconfiguration.
_extra_logger_snapshots: dict[str, _ExtraLoggerSnapshot] = {}
# The extra logger names currently attached to Hassette's pipeline, as of the most recent
# enable_basic_logging() call. Diffed against the next call's list to detect names that were
# dropped and need restoring.
_adopted_extra_loggers: set[str] = set()


def _snapshot_extra_logger(name: str) -> None:
    """Record ``name``'s current state as its restore target, if not already recorded."""
    if name in _extra_logger_snapshots:
        return
    logger = logging.getLogger(name)
    _extra_logger_snapshots[name] = _ExtraLoggerSnapshot(
        level=logger.level,
        propagate=logger.propagate,
        disabled=logger.disabled,
        handlers=list(logger.handlers),
        filters=list(logger.filters),
    )


def _restore_extra_logger(name: str) -> None:
    """Reset ``name`` back to its snapshotted pre-Hassette state.

    ``logger.handlers.clear()`` (in ``_reset_logger``) never closes the handlers it drops, so
    the original handler objects are still open and safe to reattach here. Pops the snapshot
    once replayed — see the comment on ``_extra_logger_snapshots`` for why.
    """
    snapshot = _extra_logger_snapshots.pop(name, None)
    if snapshot is None:
        return
    logger = logging.getLogger(name)
    logger.setLevel(snapshot.level)
    logger.propagate = snapshot.propagate
    logger.disabled = snapshot.disabled
    logger.handlers = list(snapshot.handlers)
    logger.filters = list(snapshot.filters)


def _reset_logger(name: str, level: int | str) -> logging.Logger:
    """Return the named logger cleared of handlers/filters, non-propagating, at ``level``.

    Called on ``HASSETTE_LOGGER_NAME`` and ``PY_WARNINGS_LOGGER_NAME``, which Hassette owns
    outright, and on every configured ``LoggingConfig.extra_loggers`` name, which it does not —
    an extra logger that already had its own handler (e.g. a library-installed ``FileHandler``)
    loses it here, in exchange for joining Hassette's structured pipeline instead.

    Also clears ``disabled`` — a very common gotcha for third-party loggers specifically,
    since ``logging.config.dictConfig()`` defaults to ``disable_existing_loggers=True`` and
    disables every logger that existed before it ran. ``Logger.handle()`` no-ops entirely on a
    disabled logger regardless of level or attached handlers, so leaving this set would make
    extra_loggers silently do nothing for exactly the kind of logger it's meant to adopt.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False
    logger.disabled = False
    logger.handlers.clear()
    logger.filters.clear()
    return logger


def enable_basic_logging(
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    *,
    log_format: Literal["auto", "console", "json"] = "auto",
    stream: IO[str] | None = None,
    extra_loggers: tuple[str, ...] | None = None,
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
        extra_loggers: Additional logger names (outside the ``hassette.`` tree) to attach to
            this same pipeline — see ``LoggingConfig.extra_loggers``. Each is reset and wired
            identically to the ``hassette`` logger itself.

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

    logger = _reset_logger(HASSETTE_LOGGER_NAME, log_level)

    stream_handler = logging.StreamHandler(out)
    stream_handler.setLevel(logging.NOTSET)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    # Capture warnings.warn(...) and friends messages in logs. Route "py.warnings" through
    # the same handler as "hassette" — otherwise captured warnings (e.g.
    # HassetteForgottenAwaitWarning) reach a logger with no handlers of its own and, via
    # propagation to root's unformatted lastResort handler, bypass the console formatter
    # and never reach the capture/persistence pipeline. Fixed at WARNING rather than
    # log_level: captureWarnings always emits at WARNING, so that's the only threshold
    # that has any effect, and this must stay independent of log_level so raising
    # log_level to reduce noise can't silently suppress HassetteForgottenAwaitWarning too —
    # ForgottenAwaitBehavior.IGNORE is the intended lever for that.
    # LoggingService.on_initialize()/on_shutdown() (Phase 2) mirror this same wiring for
    # the async pipeline.
    logging.captureWarnings(True)
    warnings_logger = _reset_logger(PY_WARNINGS_LOGGER_NAME, logging.WARNING)
    warnings_logger.addHandler(stream_handler)

    # Snapshot each newly-relevant extra_loggers name's true pre-Hassette state before anything
    # below — including the noisy-suppression block two steps down — can mutate it. A name that
    # is *also* one of the hardcoded-suppressed names below (e.g. "requests") would otherwise
    # have its restore target permanently corrupted to the suppression default (WARNING) instead
    # of whatever it actually was before this process touched it, the first time it's snapshotted.
    new_extra_loggers = set(extra_loggers or ())
    for name in new_extra_loggers:
        _snapshot_extra_logger(name)

    # A name previously adopted by an earlier enable_basic_logging() call (a different
    # Hassette() constructed earlier in this same process) that is no longer in this call's
    # list is restored to its pre-Hassette state rather than left attached to a now-orphaned
    # handler — see _restore_extra_logger.
    for dropped_name in _adopted_extra_loggers - new_extra_loggers:
        _restore_extra_logger(dropped_name)
    _adopted_extra_loggers.clear()
    _adopted_extra_loggers.update(new_extra_loggers)

    # Suppress overly verbose logs from libraries that aren't helpful. Applied before the
    # extra_loggers loop below so that explicitly opting one of these names into extra_loggers
    # (e.g. extra_loggers=["requests"] with log_level="DEBUG") always wins — otherwise this
    # block would immediately overwrite the level the user just asked for.
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.ERROR)

    # Attach any app-author-configured extra logger names (LoggingConfig.extra_loggers) to
    # the same handler, formatter, and level as the hassette logger — lets a logger outside
    # the "hassette." tree opt into structured logging without renaming into that namespace.
    # LoggingService.on_initialize()/on_shutdown() (Phase 2) mirror this same wiring.
    for extra_name in extra_loggers or []:
        extra_logger = _reset_logger(extra_name, log_level)
        extra_logger.addHandler(stream_handler)

    sys.excepthook = lambda *args: logging.getLogger().exception("Uncaught exception", exc_info=args)
    threading.excepthook = lambda args: logging.getLogger().exception(
        "Uncaught thread exception",
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),  # pyright: ignore[reportArgumentType]
    )

    return stream_handler
