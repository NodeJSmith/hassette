import asyncio
import logging
import sys
import threading
from collections import deque
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Literal

import coloredlogs

FORMAT_DATE = "%Y-%m-%d"
FORMAT_TIME = "%H:%M:%S"
FORMAT_DATETIME = f"{FORMAT_DATE} {FORMAT_TIME}"
FMT = "%(asctime)s.%(msecs)03d %(levelname)s %(name)s.%(funcName)s:%(lineno)d ─ %(message)s"

# TODO: remove coloredlogs and roll our own? or use colorlogs
# coloredlogs is unmaintained and parts of it are broken on Python >3.13


@dataclass
class LogEntry:
    """A single captured log record."""

    timestamp: float
    level: str
    logger_name: str
    func_name: str
    lineno: int
    message: str
    exc_info: str | None = None

    @property
    def app_key(self) -> str | None:
        """Extract app key from logger name if this is an app log.

        Logger names follow: hassette.AppHandler.<AppClass>[<index>]...
        """
        parts = self.logger_name.split(".")
        if len(parts) >= 3 and parts[1] == "AppHandler":
            # e.g. hassette.AppHandler.MyApp[0] -> MyApp[0]
            return parts[2]
        return None

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "logger_name": self.logger_name,
            "func_name": self.func_name,
            "lineno": self.lineno,
            "message": self.message,
            "exc_info": self.exc_info,
            "app_key": self.app_key,
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

    @property
    def buffer(self) -> deque[LogEntry]:
        return self._buffer

    def set_broadcast(self, fn: Callable[[dict], Awaitable[None]], loop: asyncio.AbstractEventLoop) -> None:
        """Called by DataSyncService after initialization to wire up WS broadcast."""
        self._broadcast_fn = fn
        self._loop = loop

    def emit(self, record: logging.LogRecord) -> None:
        entry = LogEntry(
            timestamp=record.created,
            level=record.levelname,
            logger_name=record.name,
            func_name=record.funcName or "",
            lineno=record.lineno,
            message=self.format(record),
            exc_info=record.exc_text,
        )
        self._buffer.append(entry)
        if self._broadcast_fn and self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(
                asyncio.ensure_future,
                self._broadcast_fn({"type": "log", "data": entry.to_dict()}),
            )


# Module-level reference so DataSyncService can find it
_log_capture_handler: LogCaptureHandler | None = None


def get_log_capture_handler() -> LogCaptureHandler | None:
    """Return the global LogCaptureHandler instance, if installed."""
    return _log_capture_handler


def enable_logging(
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    log_buffer_size: int = 2000,
) -> None:
    """Set up the logging"""
    global _log_capture_handler

    logger = logging.getLogger("hassette")

    # Set the base hassette logger
    logger.setLevel(log_level)

    # don't propagate to root - if someone wants to do a basicConfig on root we don't want
    # our logs going there too.
    logger.propagate = False

    # Clear any old handlers
    logger.handlers.clear()

    # NOTSET - don't clamp child logs
    # this is the kicker - if the handler is filtered then it doesn't matter what we set the
    # logger to, it won't log anything lower than the handler's level.
    # So we set the handler to NOTSET and clamp the logger itself.
    # don't know why it took me five years to learn this.
    coloredlogs.install(level=logging.NOTSET, logger=logger, fmt=FMT, datefmt=FORMAT_DATETIME)

    # reset hassette logger to desired level, as coloredlogs.install sets it to WARNING
    logger.setLevel(log_level)

    # coloredlogs does something funky to the root logger and i can't figure out what
    # so for now i'm just resorting to this
    with suppress(IndexError):
        logging.getLogger().handlers.pop(0)

    # Install log capture handler for web UI
    _log_capture_handler = LogCaptureHandler(buffer_size=log_buffer_size)
    _log_capture_handler.setFormatter(logging.Formatter(FMT, datefmt=FORMAT_DATETIME))
    logger.addHandler(_log_capture_handler)

    # here and below were pulled from Home Assistant

    # Capture warnings.warn(...) and friends messages in logs.
    # The standard destination for them is stderr, which may end up unnoticed.
    # This way they're where other messages are, and can be filtered as usual.
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
