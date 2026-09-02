"""Hassette framework server entry point."""

import asyncio
import os
import signal
from logging import getLogger

from hassette import Hassette, HassetteConfig
from hassette.exceptions import FatalError
from hassette.resources.lifecycle import request_shutdown

LOGGER = getLogger(__name__)


def _handle_sigint(core: Hassette) -> None:
    """Request shutdown on the first SIGINT; force an immediate exit on any subsequent one.

    Graceful teardown can stall or consume the full shutdown timeout, so a second Ctrl+C must
    not be swallowed by ``request_shutdown``'s idempotent no-op — it needs to exit immediately.
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
        loop.add_signal_handler(signal.SIGINT, _handle_sigint, core)
    except NotImplementedError:
        LOGGER.warning("SIGINT handler registration is not supported on this platform/event loop")

    await core.run_forever()
