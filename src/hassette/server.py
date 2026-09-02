"""Hassette framework server entry point."""

import asyncio
import functools
import os
import signal
from logging import getLogger

from hassette import Hassette, HassetteConfig
from hassette.exceptions import FatalError
from hassette.resources.lifecycle import request_shutdown

LOGGER = getLogger(__name__)


def _handle_sigint(core: Hassette, _signum: int, _frame: object) -> None:
    """Request shutdown on the first SIGINT; force an immediate exit on any subsequent one.

    Registered via ``signal.signal()`` rather than ``loop.add_signal_handler()``: shutdown
    hooks are user-authored async code that can block the event loop thread synchronously
    (see ``resources/operations.py``'s ``await method()``), and a callback registered through
    the loop only runs once the loop next gets control — never, if that blocking call is what's
    stalling teardown in the first place. A raw signal handler is delivered at the interpreter's
    next bytecode/syscall-interrupt check regardless of what the loop thread is doing, so the
    force-exit path still fires exactly when teardown is genuinely stuck.
    """
    if core.shutdown_event.is_set():
        LOGGER.warning("second SIGINT received during shutdown; forcing immediate exit")
        os._exit(1)

    request_shutdown(core, "SIGINT received")


async def main(config: HassetteConfig) -> None:
    """Start the Hassette framework server with the provided configuration."""
    if not config.token:
        raise FatalError(
            "HA token is required for server startup. Set HASSETTE__TOKEN or HA_TOKEN in your environment or .env file."
        )

    config.ensure_directories()
    core = Hassette(config=config)
    core.wire_services()

    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGTERM, request_shutdown, core, "SIGTERM received")
    except NotImplementedError:
        LOGGER.warning("SIGTERM handler registration is not supported on this platform/event loop")

    try:
        signal.signal(signal.SIGINT, functools.partial(_handle_sigint, core))
    except ValueError:
        LOGGER.warning("SIGINT handler registration is not supported outside the main thread")

    await core.run_forever()
