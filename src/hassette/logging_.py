import asyncio
import contextlib
import itertools
import logging
import logging.handlers
import queue
import sys
import threading
import traceback
import warnings
from collections.abc import Callable, Coroutine
from dataclasses import asdict, dataclass
from pathlib import PurePath
from typing import IO, TYPE_CHECKING, Any, Literal, TextIO

import structlog
import structlog.processors
import structlog.stdlib
from hassette_wire import LogAuthor

from hassette.const import HASSETTE_LOGGER_NAME
from hassette.context import CURRENT_EXECUTION_ID
from hassette.logging_processors import (
    add_execution_id,
    console_identity,
    console_renderer,
    extract_record_fields,
)
from hassette.utils.stack_frames import HASSETTE_PACKAGE_DIR

if TYPE_CHECKING:
    from hassette.core.database_service import DatabaseService

DEQUEUE_TIMEOUT_SECONDS = 0.2

# logging.captureWarnings(True) routes warnings.warn(...) calls (e.g.
# HassetteForgottenAwaitWarning) to this logger. It must stay wired to the same handlers
# as HASSETTE_LOGGER_NAME — see enable_basic_logging() below and LoggingService in
# logging_service.py, which keep both loggers in sync through both phases of the logging model.
PY_WARNINGS_LOGGER_NAME = "py.warnings"
LOGGER_NAMES = (HASSETTE_LOGGER_NAME, PY_WARNINGS_LOGGER_NAME)

# Names LoggingConfig.extra_loggers may not contain. Two distinct hazards:
# - HASSETTE_LOGGER_NAME/PY_WARNINGS_LOGGER_NAME (LOGGER_NAMES) are already managed outright by
#   enable_basic_logging()/LoggingService — letting a user re-adopt them via extra_loggers would
#   silently override level/handler wiring the framework depends on (e.g. py.warnings must stay
#   independent of log_level — see the comment on its setup below).
# - "root" is Python's stdlib special case for the process-global root logger:
#   logging.getLogger("root") returns the same object as logging.getLogger() — the identical
#   trap that makes an empty string do this too (see LoggingConfig.extra_loggers' docstring).
#   Adopting it would clear the root logger's handlers process-wide and route every propagating
#   logger through Hassette's pipeline, not just reconfigure one named logger.
# Enforced in LoggingConfig.reject_reserved_logger_name (config/models.py); this is the single
# source of truth both that validator and this module read from.
RESERVED_EXTRA_LOGGER_NAMES = frozenset({*LOGGER_NAMES, "root"})

# Top-level packages whose warning classes are Hassette's own (the workspace members ship in lockstep).
FRAMEWORK_PACKAGE_NAMES = frozenset({"hassette", "hassette_wire", "hassette_client"})

_LOG_IDENTITY_ATTR = "_hassette_log_identity"
# Set by LogIdentityFilter on every record it resolves, so a second pass leaves the record alone.
_IDENTITY_RESOLVED_ATTR = "_hassette_identity_resolved"
# Record attributes _showwarning sets on captured warnings for LogIdentityFilter to read.
WARNING_CATEGORY_ATTR = "warning_category"
WARNING_FILENAME_ATTR = "warning_filename"

LogFormat = Literal["auto", "console", "compact", "json"]


@dataclass
class LogRecordEntry:
    """A single captured log record."""

    seq: int
    timestamp: float
    level: str
    logger_name: str
    func_name: str
    lineno: int
    message: str
    author: LogAuthor
    exc_info: str | None = None
    app_key: str | None = None
    execution_id: str | None = None
    instance_name: str | None = None
    instance_index: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _extract_correlation_attrs(record: logging.LogRecord) -> dict[str, Any]:
    """Extract the identity and correlation attributes the handler filters stamped on a LogRecord."""
    return {
        "app_key": getattr(record, "app_key", None),
        # Read directly: LogIdentityFilter stamps every record, and log_records.author is NOT NULL. A record
        # that skipped the filter raises AttributeError here, which LogPersistenceHandler.emit routes to
        # handleError, so it fails alone instead of failing the whole batch insert.
        "author": record.author,  # pyright: ignore[reportAttributeAccessIssue]
        "execution_id": getattr(record, "execution_id", None),
        "instance_name": getattr(record, "instance_name", None),
        "instance_index": getattr(record, "instance_index", None),
        "seq": getattr(record, "seq", 0),
    }


def _format_exc_info(record: logging.LogRecord) -> str | None:
    if record.exc_info:
        return "".join(traceback.format_exception(*record.exc_info))
    return None


class LogCaptureHandler(logging.Handler):
    """Captures log records and broadcasts a hint to WS clients.

    Only notifies for records at or above ``_min_notify_level``, which ``LoggingService`` keeps
    in lockstep with whatever ``LogPersistenceHandler`` is actually persisting. A hint promises
    the frontend a fetchable record — it never checks levels itself, so without this floor it
    would fire for a record from *any* logger whose effective level currently lets it through
    (a per-service override in ``LoggingConfig``, or a runtime ``PUT /logs/level`` on an arbitrary
    logger), even when that record falls below the persistence threshold and can never be found by
    the `/logs/recent` refetch the hint triggers. Filtering here instead of trying to keep a
    second copy of "every logger's current effective level" in sync closes that gap for any
    logger, present or future, without enumerating them.
    """

    _broadcast_fn: Callable[[dict], Coroutine[Any, Any, None]] | None
    _loop: asyncio.AbstractEventLoop | None
    _min_notify_level: int

    shutting_down: bool

    def __init__(self) -> None:
        super().__init__()
        self._broadcast_fn = None
        self._loop = None
        self.shutting_down = False
        self._min_notify_level = logging.NOTSET

    def set_broadcast(self, fn: Callable[[dict], Coroutine[Any, Any, None]], loop: asyncio.AbstractEventLoop) -> None:
        """Called by RuntimeQueryService after initialization to wire up WS broadcast."""
        self._broadcast_fn = fn
        self._loop = loop

    def set_min_notify_level(self, level: int) -> None:
        """Called by ``LoggingService.on_initialize()`` to match the active persistence floor."""
        self._min_notify_level = level

    def emit(self, record: logging.LogRecord) -> None:
        if self.shutting_down:
            return
        if record.levelno < self._min_notify_level:
            return
        if self._broadcast_fn and self._loop and self._loop.is_running():
            fn = self._broadcast_fn
            loop = self._loop
            # LogHintWsMessage carries no log data — clients that want the new record fetch it
            # via the REST API. Keeps the broadcast payload independent of LogRecordEntry's shape, and
            # avoids building a full LogRecordEntry (message formatting, traceback rendering) here.
            payload = {"type": "log_hint", "timestamp": record.created}

            def _schedule_broadcast() -> None:
                with contextlib.suppress(RuntimeError):
                    loop.create_task(fn(payload))

            loop.call_soon_threadsafe(_schedule_broadcast)


@dataclass(frozen=True)
class LogIdentity:
    """Who wrote a logger's lines, and which app instance owns it.

    Fixed on a logger object when its resource builds it (``set_logger_identity``). An owner of
    ``None`` means the logger belongs to no app, so its lines take their subject from bound
    context instead.
    """

    author: LogAuthor
    app_key: str | None = None
    instance_name: str | None = None
    instance_index: int | None = None


def set_logger_identity(logger: logging.Logger, identity: LogIdentity) -> None:
    """Fix ``identity`` on ``logger``, replacing any identity a previous resource left there."""
    setattr(logger, _LOG_IDENTITY_ATTR, identity)


def apply_log_level(logger: logging.Logger, level: str | int, owner_name: str) -> None:
    """Set ``logger``'s level, falling back to INFO (and saying so) when ``level`` is invalid."""
    try:
        logger.setLevel(level)
    except (ValueError, TypeError) as exc:
        logger.error("Invalid log level %r for %s; falling back to INFO: %s", level, owner_name, exc)
        logger.setLevel(logging.INFO)


def get_logger_identity(logger: logging.Logger) -> LogIdentity | None:
    """Return the identity on ``logger`` or its nearest identified ancestor, or None."""
    current: logging.Logger | None = logger
    while current is not None:
        identity = getattr(current, _LOG_IDENTITY_ATTR, None)
        if identity is not None:
            return identity
        current = current.parent
    return None


def namespace_author(logger_name: str) -> LogAuthor:
    """Author for a logger nothing identified: framework inside the ``hassette`` tree, app outside it."""
    if logger_name == HASSETTE_LOGGER_NAME or logger_name.startswith(f"{HASSETTE_LOGGER_NAME}."):
        return "framework"
    return "app"


def warning_author(category: type[Warning] | None, filename: str | None) -> LogAuthor:
    """Author for a captured warning: framework for Hassette's warning classes or a warning raised in hassette."""
    if category is not None and category.__module__.partition(".")[0] in FRAMEWORK_PACKAGE_NAMES:
        return "framework"
    if filename and PurePath(filename).is_relative_to(HASSETTE_PACKAGE_DIR):
        return "framework"
    return "app"


def _record_logger(record: logging.LogRecord) -> logging.Logger | None:
    # Look the logger up without creating one: a record can name a logger nobody registered
    # (LogRecord built by hand, or replayed from another process).
    logger = logging.Logger.manager.loggerDict.get(record.name)
    return logger if isinstance(logger, logging.Logger) else None


class LogIdentityFilter(logging.Filter):
    """Stamps each record's author and subject from the logger that wrote it.

    Attached to both output paths: the console stream handler ``enable_basic_logging`` installs
    (Phase 1, before the resource tree exists) and the queue handler ``LoggingService`` swaps in
    (Phase 2), so both phases see the same identity. The writing logger's owner wins over bound
    context; context supplies the subject only for ownerless loggers (shared services, user module
    loggers, libraries).

    Idempotent: Phase 2 moves the stream handler under the queue listener, whose thread has no
    bound context, so a record this filter already resolved on the caller's thread is left alone.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, _IDENTITY_RESOLVED_ATTR, False):
            return True
        setattr(record, _IDENTITY_RESOLVED_ATTR, True)

        logger = _record_logger(record)
        identity = get_logger_identity(logger) if logger is not None else None

        if identity is not None:
            author = identity.author
        elif record.name == PY_WARNINGS_LOGGER_NAME:
            author = warning_author(
                getattr(record, WARNING_CATEGORY_ATTR, None), getattr(record, WARNING_FILENAME_ATTR, None)
            )
        else:
            author = namespace_author(record.name)
        record.author = author  # pyright: ignore[reportAttributeAccessIssue]

        if identity is not None and identity.app_key is not None:
            record.app_key = identity.app_key  # pyright: ignore[reportAttributeAccessIssue]
            record.instance_name = identity.instance_name  # pyright: ignore[reportAttributeAccessIssue]
            record.instance_index = identity.instance_index  # pyright: ignore[reportAttributeAccessIssue]
        else:
            ctx = structlog.contextvars.get_contextvars()
            record.app_key = ctx.get("app_key")  # pyright: ignore[reportAttributeAccessIssue]
            record.instance_name = ctx.get("instance_name")  # pyright: ignore[reportAttributeAccessIssue]
            record.instance_index = ctx.get("instance_index")  # pyright: ignore[reportAttributeAccessIssue]
        return True


def _showwarning(
    message: Warning | str,
    category: type[Warning],
    filename: str,
    lineno: int,
    file: TextIO | None = None,
    line: str | None = None,
) -> None:
    """``warnings.showwarning`` replacement that logs to ``py.warnings`` with the warning's origin.

    Mirrors stdlib ``logging._showwarning`` (installed by ``logging.captureWarnings``), adding the
    category and source file to the record so ``LogIdentityFilter`` can tell Hassette's warnings
    from the app's.
    """
    original = logging._warnings_showwarning  # pyright: ignore[reportAttributeAccessIssue]
    if file is not None:
        if original is not None:
            original(message, category, filename, lineno, file, line)
        return
    text = warnings.formatwarning(message, category, filename, lineno, line)
    logging.getLogger(PY_WARNINGS_LOGGER_NAME).warning(
        "%s", text, extra={WARNING_CATEGORY_ATTR: category, WARNING_FILENAME_ATTR: filename}
    )


class CorrelationFilter(logging.Filter):
    """Stamps correlation IDs and seq on log records before they leave the calling context.

    Attached to the ``QueueHandler`` (not the logger) so it runs for records propagated from
    child loggers. Reads context vars in the calling thread before the background-thread handoff.

    Stamps:
        - ``execution_id``: from ``CURRENT_EXECUTION_ID`` context var.
        - ``execution_kind``, ``listener_id``, ``job_id``: from structlog context vars
          (bound by command_executor dispatch points).
        - ``seq``: monotonic sequence number for ordering within a session.

    Author and subject are ``LogIdentityFilter``'s job.
    """

    _seq: itertools.count

    def __init__(self) -> None:
        super().__init__()
        self._seq = itertools.count(1)

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = structlog.contextvars.get_contextvars()
        record.execution_id = CURRENT_EXECUTION_ID.get(None)  # pyright: ignore[reportAttributeAccessIssue]
        record.execution_kind = ctx.get("execution_kind")  # pyright: ignore[reportAttributeAccessIssue]
        record.listener_id = ctx.get("listener_id")  # pyright: ignore[reportAttributeAccessIssue]
        record.job_id = ctx.get("job_id")  # pyright: ignore[reportAttributeAccessIssue]
        record.seq = next(self._seq)  # pyright: ignore[reportAttributeAccessIssue]
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
        log_queue = self.queue
        has_task_done = hasattr(log_queue, "task_done")
        while True:
            try:
                record = self.dequeue(True)
                if record is self._sentinel:  # pyright: ignore[reportAttributeAccessIssue]
                    if has_task_done:
                        log_queue.task_done()  # pyright: ignore[reportAttributeAccessIssue]
                    break
                self.handle(record)
                if has_task_done:
                    log_queue.task_done()  # pyright: ignore[reportAttributeAccessIssue]
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
        try:
            row = self.record_to_dict(record)
        except Exception:
            self.handleError(record)
            return
        self._batch.append(row)
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

        def _do_enqueue() -> None:
            try:
                if not db_service.enqueue(db_service._insert_log_records(batch)):
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
    log_format: LogFormat = "auto",
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
            ``"console"`` always uses ConsoleRenderer (colored human-readable, one identity column).
            ``"compact"`` is ``"console"`` with a time-only timestamp and no level padding.
            ``"json"`` always uses JSONRenderer (one JSON object per line).
            ``"auto"`` checks ``stream.isatty()`` (defaults to ``sys.stdout``); it never picks ``"compact"``.
        stream: Output stream. Defaults to ``sys.stdout``.
        extra_loggers: Additional logger names (outside the ``hassette.`` tree) to attach to
            this same pipeline — see ``LoggingConfig.extra_loggers``. Each is reset and wired
            identically to the ``hassette`` logger itself.

    Returns:
        The StreamHandler attached to the hassette logger. Stored on Hassette and
        passed to LoggingService for the Phase 2 sync→async swap.
    """
    out: IO[str] = stream if stream is not None else sys.stdout

    use_json = not out.isatty() if log_format == "auto" else log_format == "json"

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        # The compact format is read live on narrow screens, where the date is noise.
        structlog.processors.TimeStamper(fmt="%H:%M:%S" if log_format == "compact" else "iso", utc=False),
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

    if use_json:
        output_processors: list = [structlog.processors.JSONRenderer()]
    elif log_format == "compact":
        output_processors = [console_identity, console_renderer(compact=True)]
    else:
        output_processors = [console_identity, console_renderer(compact=False)]

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            extract_record_fields,
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            *output_processors,
        ],
    )

    logger = _reset_logger(HASSETTE_LOGGER_NAME, log_level)

    stream_handler = logging.StreamHandler(out)
    stream_handler.setLevel(logging.NOTSET)
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(LogIdentityFilter())
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
    # the async pipeline. _showwarning then replaces stdlib's capture hook so each record carries
    # the warning's category and source file for LogIdentityFilter. It must run after
    # captureWarnings(True), which saves the original showwarning that _showwarning and
    # captureWarnings(False) fall back to. It's assigned unconditionally because
    # captureWarnings(True) is a no-op when capture is already on.
    logging.captureWarnings(True)
    warnings.showwarning = _showwarning
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

    sys.excepthook = lambda *args: logging.getLogger().error("Uncaught exception", exc_info=args)
    threading.excepthook = lambda args: logging.getLogger().error(
        "Uncaught thread exception",
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),  # pyright: ignore[reportArgumentType]
    )

    return stream_handler
