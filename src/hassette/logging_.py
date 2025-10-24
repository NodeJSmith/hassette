import logging
import sys
import threading
from contextlib import suppress
from typing import Literal

import coloredlogs

FORMAT_DATE = "%Y-%m-%d"
FORMAT_TIME = "%H:%M:%S"
FORMAT_DATETIME = f"{FORMAT_DATE} {FORMAT_TIME}"
FMT = "%(asctime)s.%(msecs)03d %(levelname)s %(name)s.%(funcName)s:%(lineno)d ─ %(message)s"

# TODO: remove coloredlogs and roll our own? or use colorlogs
# coloredlogs is unmaintained and parts of it are broken on Python >3.13


def enable_logging(
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
) -> None:
    """Set up the logging"""

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
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )
