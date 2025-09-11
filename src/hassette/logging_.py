import logging
import sys
import threading
from contextlib import suppress
from typing import Literal

import coloredlogs

FORMAT_DATE = "%Y-%m-%d"
FORMAT_TIME = "%H:%M:%S"
FORMAT_DATETIME = f"{FORMAT_DATE} {FORMAT_TIME}"
FMT = "%(asctime)s %(levelname)s %(name)s.%(funcName)s:%(lineno)d ─ %(message)s"

# TODO: remove coloredlogs and roll our own? or use colorlogs
# coloredlogs is unmaintained and parts of it are broken on Python 3.13+


def enable_logging(
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
) -> None:
    """Set up the logging"""

    logger = logging.getLogger("hassette")

    coloredlogs.install(level=log_level, logger=logger, fmt=FMT, datefmt=FORMAT_DATETIME)

    # Move the coloredlogs handler to hassette logger, not root
    # TODO: move off coloredlogs, this stuff is too buggy
    with suppress(IndexError):
        logger.addHandler(logging.getLogger().handlers.pop(0))

    # set hassette log level back to declared level
    logger.setLevel(log_level)

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
